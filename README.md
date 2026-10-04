# KissKH Sync

KissKH Sync is a self-hosted web app for tracking KissKH series, automatically
checking for new episodes, downloading missing episodes, organizing them for
Jellyfin, and requesting a Jellyfin library refresh. It runs as a small FastAPI
service with a SQLite database and a browser-based dashboard.

> **Use responsibly:** Download only content you are authorized to access and
> store. The dashboard has no authentication; expose it only to a trusted LAN or
> put it behind an authenticated reverse proxy.

## Features

- Discover and track episodes by their KissKH source IDs.
- Watch enabled series at startup and on a configurable schedule; new episodes
  are downloaded automatically. **Check all series now** runs the watcher
  immediately.
- Choose episodes for manual downloads, or queue all missing episodes for a
  series. Completed episodes are not downloaded again.
- See queued, downloading, completed, and failed states for each episode.
  Download progress is indeterminate while active because the upstream
  downloader does not provide reliable byte-level progress.
- Set the maximum number of simultaneous episode downloads in the dashboard
  (1–16; default 1).
- Organize media into Jellyfin-readable folders and request a library refresh.

## Quick start with Docker Compose

1. Clone the repository and enter it:

   ```sh
   git clone https://github.com/joetancy/kisskh-web-downloader.git
   cd kisskh-web-downloader
   ```

2. Create the host directories used by the included Compose file. Adjust the
   paths and IDs for your server and media-library permissions as needed:

   ```sh
   mkdir -p /srv/media/appdata/kisskh-sync/data
   mkdir -p /srv/media/data/downloads/kisskh
   mkdir -p /srv/media/data/media/tv
   ```

3. Copy the example settings, then set the Jellyfin connection details:

   ```sh
   cp .env.example .env
   ```

   Edit `.env` and set `JELLYFIN_API_KEY`. If Jellyfin is not available at
   `http://jellyfin:8096` on a shared Docker network, set `JELLYFIN_URL` to an
   address the app can reach. The Jellyfin API key should have permission to
   refresh the relevant library.

4. Build and start the service:

   ```sh
   docker compose up -d --build
   ```

Open **http://<server-ip>:9020**. The container needs write access to its
database, download directory, and TV library directory. Jellyfin needs read
access to the same TV media. The included Compose file mounts the host TV folder
at the same absolute path inside the container; if you change that mapping,
update `MEDIA_DIR` to match the container path.

### Use the published image

The GitHub Actions workflow publishes
`ghcr.io/joetancy/kisskh-web-downloader:latest` from the default branch, plus
branch and version-tag images. To use the published image instead of building
locally, replace `build: .` in the service with:

```yaml
image: ghcr.io/joetancy/kisskh-web-downloader:latest
```

Then start or update it with `docker compose up -d`.

## Add and watch a series

Paste a KissKH series URL into the dashboard. Use **Discover episodes** to load
its episode list. Use **Download all missing** to queue every episode not
already completed, or expand **Episodes** to select specific episodes.

The watcher checks every series immediately on startup and every six hours by
default, and discovers all episodes. Check **Automatically download new
episodes** to also download episodes that are new to the local episode list.
With the checkbox off, discovery still runs and episodes remain available for
manual downloads. Previously discovered missing episodes are not automatically
downloaded. Use **Download all missing** or select episodes for manual downloads. Use the
**Stop** action beside a queued or downloading episode to stop it. Set
`SYNC_INTERVAL_MINUTES` to change the schedule.

For a completed episode, use **Delete files** to remove its downloaded video
and subtitle from the media directory. The episode remains in the list as
pending and can be downloaded manually again.

The dashboard's **Download queue** setting controls simultaneous episode
downloads. It defaults to 1, accepts values from 1 through 16, is saved in
SQLite, and takes effect without restarting the service.

## Configuration

The deployment Compose file and `.env.example` provide these settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `PUID` / `PGID` | `1000` / `1000` | User and group for the container process |
| `DEFAULT_QUALITY` | `1080p` | Quality used for newly added series |
| `DEFAULT_SUBTITLE_LANGUAGE` | `en` | Subtitle language preference |
| `SYNC_INTERVAL_MINUTES` | `360` | Automatic watcher interval in minutes |
| `MAX_CONCURRENT_DOWNLOADS` | `1` | Initial simultaneous-download limit; can be changed in the UI |
| `JELLYFIN_URL` | `http://jellyfin:8096` | Jellyfin base URL reachable from the app container |
| `JELLYFIN_API_KEY` | empty | Optional key for refreshing the Jellyfin library |
| `JELLYFIN_LIBRARY_ID` | empty | Optional library ID to refresh |
| `KISSKH_STREAM_KEY` / `KISSKH_SUB_KEY` | empty | Optional KissKH stream/subtitle keys |

Keep `.env` and API keys private. If the app and Jellyfin are in separate Compose
projects, attach both to a shared external Docker network and configure
`JELLYFIN_URL` to use Jellyfin's reachable service name.

## Data and troubleshooting

The SQLite database is stored at `/data/kisskh.db`; back it up before upgrades.
With the included Compose file, its host directory is
`/srv/media/appdata/kisskh-sync/data`. Downloads are staged under the configured
download directory and organized media is written to the TV library directory.

Useful checks:

```sh
curl http://localhost:9020/api/health
docker compose ps
docker compose logs -f kisskh-sync
```

If a download fails, its error appears in the episode list; select it again or
sync the series to retry. The status endpoint `/api/watcher` reports whether the
watcher is running and its next scheduled check.

## API overview

The interactive API documentation is available at **/docs**.

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Health check |
| `GET /api/watcher` / `POST /api/watcher/run` | Watcher status / immediate check |
| `GET /api/settings` / `PATCH /api/settings` | Read or update download concurrency |
| `GET, POST /api/series` | List or add a series |
| `GET, PATCH, DELETE /api/series/{id}` | Read, update, or remove a series |
| `POST /api/series/{id}/discover` | Discover episode metadata only |
| `POST /api/series/{id}/sync` | Sync and download all missing episodes |
| `GET /api/series/{id}/episodes` | List episode status and queue position |
| `POST /api/episodes/{id}/stop` | Stop a queued or active episode download |
| `DELETE /api/episodes/{id}/files` | Delete completed episode video and subtitle files |
| `POST /api/series/{id}/episodes/download` | Download selected episode IDs |
| `GET /api/jobs` / `GET /api/jobs/{id}` | List jobs or inspect one job |

## Development

Requires Python 3.13. Install the project and development dependencies, then run
the service and tests:

```sh
pip install -e '.[dev]'
uvicorn app.main:app --host 0.0.0.0 --port 9020
pytest
```

The Docker image installs `kisskh-downloader` and Playwright Chromium. The
adapter uses the library's public Python API; because the upstream dependency
can change, automated tests do not make live KissKH requests. GitHub Actions
runs the tests and builds the image for pull requests, and publishes the image
for pushes to `main` and version tags (`v*`).
