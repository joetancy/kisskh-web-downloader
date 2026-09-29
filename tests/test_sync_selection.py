from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Episode, Series, SyncJob
from app.sync import sync_series


@pytest.mark.asyncio
async def test_selected_sync_downloads_only_selected_episode(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with test_sessions() as db:
        series = Series(name="Test Show", source_url="https://kisskh.is/Drama/test?id=1")
        db.add(series)
        db.flush()
        db.add_all(
            [
                Episode(series_id=series.id, source_episode_id="ep-1", episode_number=1),
                Episode(series_id=series.id, source_episode_id="ep-2", episode_number=2),
            ]
        )
        job = SyncJob(series_id=series.id, status="queued")
        db.add(job)
        db.commit()
        series_id, job_id = series.id, job.id
        selected_id = db.scalar(select(Episode.id).where(Episode.source_episode_id == "ep-2"))

    downloaded = []

    class FakeClient:
        async def get_series(self, _url):
            return type("Metadata", (), {"name": "Test Show", "source_id": "1"})()

        async def get_episodes(self, _url):
            return [
                type(
                    "RemoteEpisode",
                    (),
                    {
                        "source_episode_id": f"ep-{number}",
                        "episode_number": number,
                        "title": f"Episode {number}",
                        "source_url": f"https://kisskh.is/ep-{number}",
                    },
                )()
                for number in (1, 2)
            ]

        async def download_episode(self, episode, *_args):
            downloaded.append(episode.source_episode_id)
            return type("Result", (), {"video_path": Path("video.mkv"), "subtitle_path": None})()

    async def refresh():
        return None

    monkeypatch.setattr("app.sync.SessionLocal", test_sessions)
    monkeypatch.setattr("app.sync.KissKHClient", FakeClient)
    monkeypatch.setattr("app.sync.refresh_library", refresh)
    monkeypatch.setattr("app.sync.organize", lambda *_args: (Path("organized.mkv"), None))

    await sync_series(series_id, job_id, selected_episode_ids={selected_id})

    assert downloaded == ["ep-2"]
    with test_sessions() as db:
        statuses = {
            row.source_episode_id: row.status
            for row in db.scalars(select(Episode).order_by(Episode.episode_number))
        }
    assert statuses == {"ep-1": "pending", "ep-2": "completed"}
