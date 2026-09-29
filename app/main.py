from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.routes import router
from app.db import Base, SessionLocal, engine
from app.models import AppSetting, Episode, SyncJob
from app.scheduler import scheduler, start_scheduler
from app.sync import configure_download_limit


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        configured_limit = db.get(AppSetting, "max_concurrent_downloads")
        if configured_limit:
            await configure_download_limit(int(configured_limit.value))
        interrupted = db.scalars(
            select(SyncJob).where(SyncJob.status.in_(("queued", "running")))
        ).all()
        for job in interrupted:
            job.status = "failed"
            job.error = "Interrupted by application restart; start a new sync to retry."
            job.completed_at = datetime.now(UTC)
        stale_episodes = db.scalars(select(Episode).where(Episode.status == "downloading")).all()
        for episode in stale_episodes:
            episode.status = "failed"
            episode.error = "Interrupted by application restart; start a new sync to retry."
        db.commit()
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="KissKH Sync", lifespan=lifespan)
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent.parent / "frontend" / "index.html").read_text()
