from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Series
from app.sync import schedule_sync

scheduler = AsyncIOScheduler()


async def run_enabled_series() -> int:
    with SessionLocal() as db:
        series_ids = list(db.scalars(select(Series.id).where(Series.enabled.is_(True))))
    for series_id in series_ids:
        # Sync all missing episodes for enabled series; completed episodes are
        # skipped by sync_series, so repeated watcher scans are safe.
        schedule_sync(series_id)
    return len(series_ids)


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
    scheduler.start()


def watcher_status() -> dict:
    job = scheduler.get_job("series-sync")
    return {
        "enabled": bool(scheduler.running and job),
        "interval_minutes": get_settings().sync_interval_minutes,
        "next_run_at": job.next_run_time if job else None,
    }
