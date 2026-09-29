import httpx

from app.config import get_settings


async def refresh_library() -> None:
    settings = get_settings()
    if not settings.jellyfin_api_key:
        raise RuntimeError("Jellyfin API key is not configured")
    headers = {"X-Emby-Token": settings.jellyfin_api_key}
    async with httpx.AsyncClient(timeout=15) as client:
        if settings.jellyfin_library_id:
            response = await client.post(
                f"{settings.jellyfin_url.rstrip('/')}/Items/{settings.jellyfin_library_id}/Refresh",
                headers=headers,
            )
        else:
            response = await client.post(
                f"{settings.jellyfin_url.rstrip('/')}/Library/Refresh", headers=headers
            )
        response.raise_for_status()
