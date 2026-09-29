from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 9020
    download_dir: Path = Path("/downloads")
    media_dir: Path = Path("/srv/media/data/media/tv")
    database_url: str = "sqlite:////data/kisskh.db"
    default_quality: str = "1080p"
    default_subtitle_language: str = "en"
    sync_interval_minutes: int = 360
    jellyfin_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str = ""
    jellyfin_library_id: str = ""
    kisskh_stream_key: str = ""
    kisskh_sub_key: str = ""
    max_concurrent_downloads: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
