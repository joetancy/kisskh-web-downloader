from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppSetting, Episode, Series, SyncJob
from app.scheduler import run_enabled_series, watcher_status
from app.sync import configure_download_limit, schedule_sync, stop_episode

router = APIRouter(prefix="/api")


class SeriesCreate(BaseModel):
    source_url: HttpUrl
    name: str | None = None
    season: int = 1
    quality: str | None = None
    subtitle_language: str | None = None
    destination_name: str | None = None


class SeriesPatch(BaseModel):
    enabled: bool | None = None
    season: int | None = None
    quality: str | None = None
    subtitle_language: str | None = None
    destination_name: str | None = None


class EpisodeSelection(BaseModel):
    episode_ids: list[int] = Field(min_length=1, max_length=200)


class SettingsPatch(BaseModel):
    max_concurrent_downloads: int = Field(ge=1, le=16)


def series_data(row: Series):
    return {
        "id": row.id,
        "name": row.name,
        "source_url": row.source_url,
        "source_id": row.source_id,
        "season": row.season,
        "quality": row.quality,
        "subtitle_language": row.subtitle_language,
        "destination_name": row.destination_name,
        "enabled": row.enabled,
        "last_sync_at": row.last_sync_at,
    }


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/watcher")
def get_watcher():
    return watcher_status()


@router.post("/watcher/run", status_code=202)
async def run_watcher():
    count = await run_enabled_series()
    return {"series_queued": count}


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    setting = db.get(AppSetting, "max_concurrent_downloads")
    value = int(setting.value) if setting else get_settings().max_concurrent_downloads
    return {"max_concurrent_downloads": value}


@router.patch("/settings")
async def update_settings(payload: SettingsPatch, db: Session = Depends(get_db)):
    setting = db.get(AppSetting, "max_concurrent_downloads")
    if setting:
        setting.value = str(payload.max_concurrent_downloads)
    else:
        db.add(
            AppSetting(key="max_concurrent_downloads", value=str(payload.max_concurrent_downloads))
        )
    db.commit()
    await configure_download_limit(payload.max_concurrent_downloads)
    return {"max_concurrent_downloads": payload.max_concurrent_downloads}


@router.get("/series")
def list_series(db: Session = Depends(get_db)):
    return [series_data(row) for row in db.scalars(select(Series).order_by(Series.name))]


@router.post("/series", status_code=201)
def create_series(payload: SeriesCreate, db: Session = Depends(get_db)):
    settings = get_settings()
    row = Series(
        source_url=str(payload.source_url),
        name=payload.name or str(payload.source_url),
        season=payload.season,
        quality=payload.quality or settings.default_quality,
        subtitle_language=payload.subtitle_language or settings.default_subtitle_language,
        destination_name=payload.destination_name,
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(409, "Series URL already exists") from exc
    db.refresh(row)
    return series_data(row)


@router.get("/series/{series_id}")
def get_series(series_id: int, db: Session = Depends(get_db)):
    row = db.get(Series, series_id)
    if not row:
        raise HTTPException(404, "Series not found")
    return series_data(row)


@router.patch("/series/{series_id}")
def patch_series(series_id: int, payload: SeriesPatch, db: Session = Depends(get_db)):
    row = db.get(Series, series_id)
    if not row:
        raise HTTPException(404, "Series not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    return series_data(row)


@router.delete("/series/{series_id}", status_code=204)
def delete_series(series_id: int, db: Session = Depends(get_db)):
    row = db.get(Series, series_id)
    if not row:
        raise HTTPException(404, "Series not found")
    db.delete(row)
    db.commit()


@router.post("/series/{series_id}/sync", status_code=202)
@router.post("/series/{series_id}/rescan", status_code=202)
async def sync(series_id: int, db: Session = Depends(get_db)):
    if not db.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    return {"job_id": schedule_sync(series_id)}


@router.post("/series/{series_id}/discover", status_code=202)
async def discover(series_id: int, db: Session = Depends(get_db)):
    if not db.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    return {"job_id": schedule_sync(series_id, discover_only=True)}


@router.post("/series/{series_id}/episodes/download", status_code=202)
async def download_selected(
    series_id: int, payload: EpisodeSelection, db: Session = Depends(get_db)
):
    if not db.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    selected = set(payload.episode_ids)
    rows = list(
        db.scalars(select(Episode).where(Episode.series_id == series_id, Episode.id.in_(selected)))
    )
    if len(rows) != len(selected):
        raise HTTPException(404, "One or more episodes do not belong to this series")
    if any(row.status in {"completed", "queued", "downloading"} for row in rows):
        raise HTTPException(409, "Completed or already queued episodes cannot be queued again")
    return {"job_id": schedule_sync(series_id, selected_episode_ids=selected)}


@router.get("/series/{series_id}/episodes")
def episodes(series_id: int, db: Session = Depends(get_db)):
    if not db.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    rows = list(
        db.scalars(
            select(Episode).where(Episode.series_id == series_id).order_by(Episode.episode_number)
        )
    )
    queue_positions = {}
    position = 0
    for row in rows:
        if row.status in {"queued", "downloading"}:
            position += 1
            queue_positions[row.id] = position
    return [
        {
            "id": row.id,
            "source_episode_id": row.source_episode_id,
            "episode_number": row.episode_number,
            "title": row.title,
            "status": row.status,
            "video_path": row.video_path,
            "subtitle_path": row.subtitle_path,
            "error": row.error,
            "queue_position": queue_positions.get(row.id),
        }
        for row in rows
    ]


@router.post("/episodes/{episode_id}/stop")
def stop_download(episode_id: int, db: Session = Depends(get_db)):
    row = db.get(Episode, episode_id)
    if not row:
        raise HTTPException(404, "Episode not found")
    if row.status not in {"queued", "downloading"}:
        raise HTTPException(409, "Episode is not queued or downloading")
    stop_episode(episode_id)
    row.status = "stopped"
    row.error = None
    db.commit()
    return {"status": "stopped"}


@router.delete("/episodes/{episode_id}/files", status_code=204)
def delete_episode_files(episode_id: int, db: Session = Depends(get_db)):
    row = db.get(Episode, episode_id)
    if not row:
        raise HTTPException(404, "Episode not found")
    if row.status in {"queued", "downloading"}:
        raise HTTPException(409, "Stop the episode before deleting its files")
    if row.status != "completed":
        raise HTTPException(409, "Episode has no completed download to delete")

    media_root = get_settings().media_dir.resolve()
    files = [Path(path).resolve() for path in (row.video_path, row.subtitle_path) if path]
    if any(not path.is_relative_to(media_root) for path in files):
        raise HTTPException(400, "Episode file is outside the configured media directory")
    try:
        for path in files:
            path.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(500, "Could not delete episode files") from exc

    row.status = "pending"
    row.video_path = None
    row.subtitle_path = None
    row.downloaded_at = None
    row.error = None
    db.commit()


@router.get("/jobs")
def jobs(db: Session = Depends(get_db)):
    return [
        {
            "id": row.id,
            "series_id": row.series_id,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "status": row.status,
            "episodes_found": row.episodes_found,
            "episodes_downloaded": row.episodes_downloaded,
            "error": row.error,
            "refresh_error": row.refresh_error,
        }
        for row in db.scalars(select(SyncJob).order_by(SyncJob.id.desc()))
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    row = db.get(SyncJob, job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    return {
        "id": row.id,
        "series_id": row.series_id,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "status": row.status,
        "episodes_found": row.episodes_found,
        "episodes_downloaded": row.episodes_downloaded,
        "error": row.error,
        "refresh_error": row.refresh_error,
    }
