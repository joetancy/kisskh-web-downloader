"""Isolated CLI bridge for the optional kisskh-downloader executable."""

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import get_settings


@dataclass
class SeriesMetadata:
    name: str
    source_id: str | None = None


@dataclass
class EpisodeMetadata:
    source_episode_id: str
    episode_number: int
    title: str
    source_url: str


@dataclass
class DownloadResult:
    video_path: Path
    subtitle_path: Path | None = None


class KissKHError(RuntimeError):
    pass


class KissKHClient:
    """Thin Python-library bridge around kisskh-downloader's public classes."""

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout
        settings = get_settings()
        if settings.kisskh_stream_key:
            os.environ["KISSKH_STREAM_KEY"] = settings.kisskh_stream_key
        if settings.kisskh_sub_key:
            os.environ["KISSKH_SUB_KEY"] = settings.kisskh_sub_key

    @staticmethod
    def _api(url: str):
        from kisskh_downloader.kisskh_api import KissKHApi

        parsed = urlparse(url)
        ids = parse_qs(parsed.query).get("id")
        if not ids:
            raise KissKHError("Series URL must include an id query parameter")
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        return KissKHApi(base_url=base_url), int(ids[0])

    async def get_series(self, url: str) -> SeriesMetadata:
        def load():
            from kisskh_downloader.models.drama import Drama

            api, drama_id = self._api(url)
            try:
                response = api._request(api._drama_api_url(drama_id))
                drama = Drama.model_validate(response.json())
                return SeriesMetadata(drama.title, str(drama.id))
            except Exception as exc:
                raise KissKHError("Series not found or KissKH metadata unavailable") from exc
            finally:
                api.cleanup()

        return await asyncio.wait_for(asyncio.to_thread(load), timeout=self.timeout)

    async def get_episodes(self, url: str) -> list[EpisodeMetadata]:
        def load():
            from kisskh_downloader.models.drama import Drama

            api, drama_id = self._api(url)
            try:
                response = api._request(api._drama_api_url(drama_id))
                drama = Drama.model_validate(response.json())
                slug = re.sub(r"[^A-Za-z0-9_-]", "_", drama.title.replace(" ", "-"))
                return [
                    EpisodeMetadata(
                        str(ep.id),
                        int(ep.number),
                        f"Episode {ep.number}",
                        f"{api.site_domain}/Drama/{slug}/Episode-{ep.number}?id={drama.id}&ep={ep.id}&page=0&pageSize=100",
                    )
                    for ep in drama.episodes
                ]
            except Exception as exc:
                raise KissKHError("Unable to discover KissKH episodes") from exc
            finally:
                api.cleanup()

        return await asyncio.wait_for(asyncio.to_thread(load), timeout=self.timeout)

    async def download_episode(
        self,
        episode: EpisodeMetadata,
        output_dir: Path,
        quality: str,
        subtitle_language: str | None,
    ) -> DownloadResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        def download():
            from kisskh_downloader.downloader import Downloader

            try:
                api, drama_id = self._api(episode.source_url)
                episode_id = int(episode.source_episode_id)
                number_match = re.search(r"Episode-([\d.]+)", episode.source_url)
                number = (
                    int(float(number_match.group(1))) if number_match else episode.episode_number
                )
                keys = api.generate_kkeys(drama_id, episode_id, number, "Drama")
                stream = api.get_stream_url(episode_id, keys.get("stream", ""))
                if not stream or "tickcounter" in stream:
                    raise KissKHError("Episode unavailable")
                prefix = output_dir / f"episode-{episode.episode_number:03d}"
                downloader = Downloader(referer=api.site_domain)
                downloader.download_video_from_stream_url(stream, str(prefix), quality)
                video_files = [p for p in output_dir.iterdir() if p.is_file() and p != prefix]
                videos = [
                    p
                    for p in video_files
                    if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m4v"}
                ]
                if not videos:
                    raise KissKHError("Downloader did not produce a video file")
                subtitle_path = None
                try:
                    subtitles = api.get_subtitles(
                        episode_id,
                        keys.get("sub", ""),
                        *([subtitle_language] if subtitle_language else ["en"]),
                    )
                    downloader.download_subtitles(subtitles, str(prefix))
                    subs = list(output_dir.glob(prefix.name + ".*.srt"))
                    subtitle_path = subs[0] if subs else None
                except Exception:
                    # Optional subtitles must not invalidate a successful video.
                    subtitle_path = None
                return DownloadResult(videos[0], subtitle_path)
            except KissKHError:
                raise
            except Exception as exc:
                # Third-party exceptions can contain tokenized URLs: don't persist them.
                raise KissKHError("KissKH episode download failed") from exc
            finally:
                if "api" in locals():
                    api.cleanup()

        return await asyncio.wait_for(asyncio.to_thread(download), timeout=self.timeout)
