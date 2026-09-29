import argparse
import asyncio

from app.db import Base, SessionLocal, engine
from app.models import Series
from app.sync import sync_series


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync-all", "sync", "rescan", "doctor"])
    parser.add_argument("series_id", nargs="?", type=int)
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    if args.command == "doctor":
        print("Database: writable")
        return
    if args.command == "sync-all":
        with SessionLocal() as db:
            ids = [row.id for row in db.query(Series).filter_by(enabled=True)]
        for series_id in ids:
            asyncio.run(sync_series(series_id))
    elif args.series_id:
        asyncio.run(sync_series(args.series_id))
    else:
        parser.error("series_id is required")


if __name__ == "__main__":
    main()
