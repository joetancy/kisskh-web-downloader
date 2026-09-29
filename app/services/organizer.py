import re
import shutil
from pathlib import Path


def sanitize_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if name in {"", ".", ".."}:
        raise ValueError("Invalid empty destination name")
    return name


def jellyfin_names(
    show: str, season: int, episode: int, extension: str, language: str | None = None
) -> tuple[str, str | None]:
    show = sanitize_name(show)
    stem = f"{show} - S{season:02d}E{episode:02d}"
    video = stem + extension
    subtitle = f"{stem}.{sanitize_name(language)}.srt" if language else None
    return video, subtitle


def organize(
    video: Path,
    subtitle: Path | None,
    media_dir: Path,
    show: str,
    season: int,
    episode: int,
    language: str | None,
) -> tuple[Path, Path | None]:
    video_name, subtitle_name = jellyfin_names(show, season, episode, video.suffix, language)
    destination = media_dir.resolve() / sanitize_name(show) / f"Season {season:02d}"
    destination.mkdir(parents=True, exist_ok=True)
    video_target = destination / video_name
    shutil.move(str(video), video_target)
    subtitle_target = None
    if subtitle and subtitle_name:
        subtitle_target = destination / subtitle_name
        shutil.move(str(subtitle), subtitle_target)
    return video_target, subtitle_target
