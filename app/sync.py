import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.adapters.kisskh import EpisodeMetadata, KissKHClient
from app.config import get_settings
from app.db import SessionLocal
from app.models import Episode, Series, SyncJob
from app.services.jellyfin import refresh_library
from app.services.organizer import organize

_locks: dict[int, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()
_episode_tasks: dict[int, asyncio.Task] = {}


class DownloadLimiter:
    """Resizable process-wide semaphore for episode downloads."""

    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0
        self.condition = asyncio.Condition()

    async def set_limit(self, limit: int) -> None:
        async with self.condition:
            self.limit = limit
            self.condition.notify_all()

    async def __aenter__(self):
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1
        return self

    async def __aexit__(self, *_exc):
        async with self.condition:
            self.active -= 1
            self.condition.notify_all()


_download_limiter = DownloadLimiter(max(1, get_settings().max_concurrent_downloads))


async def configure_download_limit(limit: int) -> None:
    await _download_limiter.set_limit(limit)


def _task_finished(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled():
        task.exception()


async def _download_one(
    client: KissKHClient,
    series_id: int,
    episode_id: int,
    metadata: EpisodeMetadata,
    job_id: int,
) -> bool:
    async with _download_limiter:
        with SessionLocal() as db:
            episode = db.get(Episode, episode_id)
            series = db.get(Series, series_id)
            if not episode or not series or episode.status == "completed":
                return False
            episode.status = "downloading"
            episode.error = None
            db.commit()
            quality = series.quality
            language = series.subtitle_language
            show_name = series.destination_name or series.name
            season = series.season

        partial = get_settings().download_dir / ".partial" / str(job_id) / str(episode_id)
        try:
            result = await client.download_episode(metadata, partial, quality, language)
            video_path, subtitle_path = organize(
                result.video_path,
                result.subtitle_path,
                get_settings().media_dir,
                show_name,
                season,
                metadata.episode_number,
                language,
            )
            with SessionLocal() as db:
                episode = db.get(Episode, episode_id)
                if episode:
                    episode.status = "completed"
                    episode.video_path = str(video_path)
                    episode.subtitle_path = str(subtitle_path) if subtitle_path else None
                    episode.downloaded_at = datetime.now(UTC)
                    db.commit()
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with SessionLocal() as db:
                episode = db.get(Episode, episode_id)
                if episode:
                    episode.status = "failed"
                    episode.error = str(exc)[:2000]
                    db.commit()
            return False


async def sync_series(
    series_id: int,
    job_id: int | None = None,
    selected_episode_ids: set[int] | None = None,
    discover_only: bool = False,
    new_episodes_only: bool = False,
) -> None:
    lock = _locks.setdefault(series_id, asyncio.Lock())
    async with lock:
        client = KissKHClient()
        queue: list[tuple[int, EpisodeMetadata]] = []
        with SessionLocal() as db:
            series = db.get(Series, series_id)
            job = db.get(SyncJob, job_id) if job_id else None
            if not series:
                if job:
                    job.status = "failed"
                    job.error = "Series not found"
                    job.completed_at = datetime.now(UTC)
                    db.commit()
                return
            try:
                metadata = await client.get_series(series.source_url)
                series.name = metadata.name
                series.source_id = metadata.source_id
                discovered = await client.get_episodes(series.source_url)
                if job:
                    job.status = "running"
                    job.episodes_found = len(discovered)
                existing = {
                    row.source_episode_id: row
                    for row in db.scalars(select(Episode).where(Episode.series_id == series_id))
                }
                for item in discovered:
                    episode = existing.get(item.source_episode_id)
                    is_new = episode is None
                    if episode is None:
                        episode = Episode(
                            series_id=series_id,
                            source_episode_id=item.source_episode_id,
                            episode_number=item.episode_number,
                            title=item.title,
                            source_url=item.source_url,
                            quality=series.quality,
                        )
                        db.add(episode)
                        db.flush()
                        existing[item.source_episode_id] = episode
                    if discover_only or episode.status == "completed":
                        continue
                    if new_episodes_only and not is_new:
                        continue
                    if selected_episode_ids is not None and episode.id not in selected_episode_ids:
                        continue
                    episode.status = "queued"
                    episode.error = None
                    queue.append((episode.id, item))
                series.last_sync_at = datetime.now(UTC)
                db.commit()
            except Exception as exc:
                if job:
                    job.status = "failed"
                    job.error = str(exc)[:2000]
                    job.completed_at = datetime.now(UTC)
                db.commit()
                return

        async def download_tracked(episode_id: int, item: EpisodeMetadata) -> bool:
            task = asyncio.current_task()
            if task:
                _episode_tasks[episode_id] = task
            try:
                return await _download_one(client, series_id, episode_id, item, job_id or 0)
            finally:
                if _episode_tasks.get(episode_id) is task:
                    _episode_tasks.pop(episode_id, None)

        added_results = await asyncio.gather(
            *(download_tracked(episode_id, item) for episode_id, item in queue),
            return_exceptions=True,
        ) if queue else []
        added = sum(result is True for result in added_results)

        with SessionLocal() as db:
            job = db.get(SyncJob, job_id) if job_id else None
            if job:
                job.episodes_downloaded = added
                job.status = "completed"
                job.completed_at = datetime.now(UTC)
            db.commit()

        if added:
            try:
                await refresh_library()
            except Exception:
                if job_id:
                    with SessionLocal() as db:
                        job = db.get(SyncJob, job_id)
                        if job:
                            job.refresh_error = "Jellyfin library refresh failed"
                            db.commit()


def schedule_sync(
    series_id: int,
    selected_episode_ids: set[int] | None = None,
    discover_only: bool = False,
    new_episodes_only: bool = False,
) -> int:
    loop = asyncio.get_running_loop()
    with SessionLocal() as db:
        job = SyncJob(series_id=series_id, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    task = loop.create_task(
        sync_series(series_id, job_id, selected_episode_ids, discover_only, new_episodes_only)
    )
    _tasks.add(task)
    task.add_done_callback(_task_finished)
    return job_id


def stop_episode(episode_id: int) -> bool:
    task = _episode_tasks.get(episode_id)
    if task and not task.done():
        task.cancel()
        return True
    return False
