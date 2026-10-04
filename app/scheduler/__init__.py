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
        series_rows = list(db.execute(select(Series.id, Series.enabled)))
    for series_id, auto_download in series_rows:
        # Every series is scanned; the checkbox only controls new downloads.
        schedule_sync(
            series_id,
            discover_only=not auto_download,
            new_episodes_only=auto_download,
        )
    return len(series_rows)


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
