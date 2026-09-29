import asyncio

import pytest

from app.sync import DownloadLimiter


@pytest.mark.asyncio
async def test_download_limiter_honors_parallel_setting():
    limiter = DownloadLimiter(2)
    active = 0
    peak = 0

    async def download():
        nonlocal active, peak
        async with limiter:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(download() for _ in range(6)))
    assert peak == 2
