# KissKH Sync

A self-hosted FastAPI application to track authorized KissKH series downloads,
organize completed media for Jellyfin, and request a library refresh. It does not
depend on Sonarr or Radarr. The app listens on **9020**.

> Use only for content you are authorized to download. Keep the web interface on
> a trusted network; it currently has no user authentication.

## Deploy with Docker Compose

On Debian, create storage directories:

```sh
mkdir -p /srv/media/appdata/kisskh-sync/data
mkdir -p /srv/media/data/downloads/kisskh
mkdir -p /srv/media/data/media/tv
# Set .env PUID/PGID to the service UID and shared media GID; grant those
# identities write access to appdata, downloads, and the TV media directory.
chown -R 1000:1000 /srv/media/appdata/kisskh-sync/data /srv/media/data/downloads/kisskh
```

Set `JELLYFIN_URL` and `JELLYFIN_API_KEY` in `.env` (copy `.env.example` as a
starting point), then run:

```sh
docker compose up -d --build
```

Open `http://<server-ip>:9020`. The container needs write access to the
downloads and TV directories, and Jellyfin must have read access to
`/srv/media/data/media/tv`. Configure a Jellyfin API key with permission to
refresh libraries. If Jellyfin is in a different Compose project, attach this
service and Jellyfin to a shared external Docker network and set `JELLYFIN_URL`
to its reachable service name. Jellyfin is not required in this Compose file.
The app mounts the media folder at `/srv/media/data/media/tv` inside its
container as well, matching Jellyfin's configured library path.

## Add and sync a series

Add a KissKH series URL in the UI. The service discovers episodes during Sync,
tracks them by source episode ID in SQLite, and skips completed episodes. Set
season, quality, subtitle language, or a destination folder with the REST API
(`PATCH /api/series/{id}`). Scheduled synchronization defaults to every six
hours and is configured with `SYNC_INTERVAL_MINUTES`. The automatic watcher
checks enabled series at startup and on that interval; use **Check all series
now** in the UI to immediately check and download new episodes. Newly discovered
episodes for enabled series are downloaded automatically; completed episodes
are skipped. Disable a series to exclude it from watcher downloads. Manual operations are
`POST /api/series/{id}/sync` and `/rescan`; both return a job ID immediately.
The **Download queue** control sets the maximum number of simultaneous episode
downloads (1 by default, up to 16); its value is saved in SQLite and takes
effect without restarting the container.

## Downloader adapter

The adapter uses the public Python classes from
[`debakarr/kisskh-dl`](https://github.com/debakarr/kisskh-dl) (`KissKHApi` and
`Downloader`) rather than assuming a CLI protocol. The Docker image installs
`kisskh-downloader` and Playwright Chromium. The library can use
`KISSKH_STREAM_KEY` and `KISSKH_SUB_KEY`, or its Playwright key flow when needed.
Keys should be kept private and are not included in API responses/logs.

## Configuration and operation

Important settings are in `.env.example`. Persistent SQLite storage is
`/data/kisskh.db`; back it up by stopping the container and copying
`/srv/media/appdata/kisskh-sync/data`. The container exposes only port 9020.
Check `curl http://localhost:9020/api/health`, `docker compose logs -f
kisskh-sync`, and `docker compose ps` when troubleshooting. Keep Jellyfin's API
key private; API responses do not include configured secrets.

Upgrade by pulling/building the new image with `docker compose up -d --build`;
back up the database first. For local development, install Python 3.13 and run
`pip install -e '.[dev]'`, `uvicorn app.main:app --host 0.0.0.0 --port 9020`.

The `Docker image` GitHub Actions workflow builds on pull requests and publishes
`ghcr.io/<owner>/<repository>` on pushes to `main` and version tags (`v*`).

## Current MVP limitations

The third-party downloader is an evolving external dependency; no live KissKH
request is made by automated tests. Verify current behavior on your deployment.
The UI is intended for a trusted LAN and has no authentication. A failed episode
is visible in the episode list and can be retried by syncing its series again.
