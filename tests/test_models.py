from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Episode, Series


def test_episode_source_id_is_unique_per_series():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        series = Series(name="Test", source_url="https://example.test/show")
        db.add(series)
        db.flush()
        db.add(Episode(series_id=series.id, source_episode_id="e1", episode_number=1))
        db.commit()
        db.add(Episode(series_id=series.id, source_episode_id="e1", episode_number=1))
        try:
            db.commit()
            assert False, "unique constraint should reject duplicate"
        except IntegrityError:
            db.rollback()
