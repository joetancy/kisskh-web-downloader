from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Series
from app.scheduler import run_enabled_series


async def test_watcher_scans_all_series_and_checkbox_only_controls_auto_download(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with test_sessions() as db:
        db.add_all(
            [
                Series(name="Automatic", source_url="https://example.test/automatic", enabled=True),
                Series(
                    name="Discover only", source_url="https://example.test/discover", enabled=False
                ),
            ]
        )
        db.commit()

    scheduled = []
    monkeypatch.setattr("app.scheduler.SessionLocal", test_sessions)
    monkeypatch.setattr(
        "app.scheduler.schedule_sync",
        lambda series_id, **kwargs: scheduled.append((series_id, kwargs)),
    )

    count = await run_enabled_series()

    assert count == 2
    assert scheduled == [
        (1, {"discover_only": False, "new_episodes_only": True}),
        (2, {"discover_only": True, "new_episodes_only": False}),
    ]
