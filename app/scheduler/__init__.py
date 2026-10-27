from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Episode, Series
from app.sync import schedule_sync

scheduler = AsyncIOScheduler()


async def run_enabled_series() -> int:
    with SessionLocal() as db:
        series_rows = list(db.execute(select(Series.id, Series.enabled)))
    for series_id, auto_download in series_rows:
        # Every series is scanned; the checkbox only controls new downloads.
        schedule_sync(
            series_id,
            discover_only=not auto_download,
            new_episodes_only=auto_download,
        )
    return len(series_rows)


async def retry_failed_downloads() -> int:
    """Retry failed episodes once per day, even for series without auto-download enabled."""
    with SessionLocal() as db:
        failed = db.execute(
            select(Series.id, Episode.id)
            .join(Episode, Episode.series_id == Series.id)
            .where(Episode.status == "failed")
        ).all()
    by_series: dict[int, set[int]] = {}
    for series_id, episode_id in failed:
        by_series.setdefault(series_id, set()).add(episode_id)
    for series_id, episode_ids in by_series.items():
        schedule_sync(series_id, selected_episode_ids=episode_ids)
    return len(failed)


def start_scheduler() -> None:
    scheduler.add_job(
        run_enabled_series,
        "interval",
        minutes=get_settings().sync_interval_minutes,
        next_run_time=datetime.now(UTC),
        id="series-sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        retry_failed_downloads,
        "interval",
        days=1,
        id="failed-download-retry",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()


def watcher_status() -> dict:
    job = scheduler.get_job("series-sync")
    return {
        "enabled": bool(scheduler.running and job),
        "interval_minutes": get_settings().sync_interval_minutes,
        "next_run_at": job.next_run_time if job else None,
    }
