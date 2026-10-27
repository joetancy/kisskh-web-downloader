"""Isolated CLI bridge for the optional kisskh-downloader executable."""

import asyncio
import logging
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


logger = logging.getLogger(__name__)


def _safe_error_detail(exc: Exception) -> str:
    detail = str(exc)
    detail = re.sub(r"https?://[^\s\"'<>]+", "<url>", detail)
    detail = re.sub(
        r"(?i)\b(authorization|token|api[_-]?key|signature|sig|auth)\b\s*[:=]\s*[^\s,;&]+",
        r"\1=<redacted>",
        detail,
    )
    settings = get_settings()
    for secret in (settings.kisskh_stream_key, settings.kisskh_sub_key):
        if secret:
            detail = detail.replace(secret, "<redacted>")
    return detail[:500] or "No error details supplied"


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
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(
                "KissKH episode download failed episode_id=%s episode_number=%s stage=%s "
                "error_type=%s detail=%s",
                episode.source_episode_id,
                episode.episode_number,
                "prepare output directory",
                type(exc).__name__,
                _safe_error_detail(exc),
            )
            raise KissKHError("Could not prepare the episode download directory") from exc

        def download():
            stage = "load downloader"
            try:
                from kisskh_downloader.downloader import Downloader

                stage = "initialize API client"
                api, drama_id = self._api(episode.source_url)
                episode_id = int(episode.source_episode_id)
                number_match = re.search(r"Episode-([\d.]+)", episode.source_url)
                number = (
                    int(float(number_match.group(1))) if number_match else episode.episode_number
                )
                stage = "generate stream keys"
                keys = api.generate_kkeys(drama_id, episode_id, number, "Drama")
                stage = "resolve episode stream"
                stream = api.get_stream_url(episode_id, keys.get("stream", ""))
                if not stream or "tickcounter" in stream:
                    raise KissKHError("Episode unavailable")
                prefix = output_dir / f"episode-{episode.episode_number:03d}"
                downloader = Downloader(referer=api.site_domain)
                stage = "download video"
                downloader.download_video_from_stream_url(stream, str(prefix), quality)
                stage = "find downloaded video"
                video_files = [p for p in output_dir.iterdir() if p.is_file() and p != prefix]
                videos = [
                    p
                    for p in video_files
                    if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m4v"}
                ]
                if not videos:
                    raise KissKHError("Downloader did not produce a video file")
                subtitle_path = None
                stage = "download optional subtitle"
                try:
                    subtitles = api.get_subtitles(
                        episode_id,
                        keys.get("sub", ""),
                        *([subtitle_language] if subtitle_language else ["en"]),
                    )
                    downloader.download_subtitles(subtitles, str(prefix))
                    subs = list(output_dir.glob(prefix.name + ".*.srt"))
                    subtitle_path = subs[0] if subs else None
                except Exception as exc:
                    # Optional subtitles must not invalidate a successful video.
                    logger.warning(
                        "KissKH subtitle download failed series_episode_id=%s episode_number=%s "
                        "stage=%s error_type=%s detail=%s",
                        episode.source_episode_id,
                        episode.episode_number,
                        stage,
                        type(exc).__name__,
                        _safe_error_detail(exc),
                    )
                    subtitle_path = None
                return DownloadResult(videos[0], subtitle_path)
            except KissKHError as exc:
                logger.error(
                    "KissKH episode download failed episode_id=%s episode_number=%s stage=%s "
                    "error_type=%s detail=%s",
                    episode.source_episode_id,
                    episode.episode_number,
                    stage,
                    type(exc).__name__,
                    _safe_error_detail(exc),
                )
                raise
            except Exception as exc:
                # Third-party exceptions can contain tokenized URLs: don't persist them.
                logger.error(
                    "KissKH episode download failed episode_id=%s episode_number=%s stage=%s "
                    "error_type=%s detail=%s",
                    episode.source_episode_id,
                    episode.episode_number,
                    stage,
                    type(exc).__name__,
                    _safe_error_detail(exc),
                )
                raise KissKHError("KissKH episode download failed") from exc
            finally:
                if "api" in locals():
                    api.cleanup()

        try:
            return await asyncio.wait_for(asyncio.to_thread(download), timeout=self.timeout)
        except TimeoutError as exc:
            logger.error(
                "KissKH episode download timed out episode_id=%s episode_number=%s "
                "timeout_seconds=%s",
                episode.source_episode_id,
                episode.episode_number,
                self.timeout,
            )
            raise KissKHError("KissKH episode download timed out") from exc
