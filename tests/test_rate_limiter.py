import asyncio
import time
import pytest

from src.utils.rate_limiter import RateLimiter


def test_rate_limiter_requires_limit():
    with pytest.raises(ValueError):
        RateLimiter()


def test_rate_limiter_sync_waits():
    limiter = RateLimiter(requests_per_second=2)
    start = time.monotonic()
    for _ in range(3):
        limiter.wait_if_needed()
    duration = time.monotonic() - start
    assert duration >= 1.0


def test_rate_limiter_async_waits():
    limiter = RateLimiter(requests_per_second=2)
    start = time.monotonic()

    async def run_waits():
        for _ in range(3):
            await limiter.wait_if_needed_async()

    asyncio.run(run_waits())
    duration = time.monotonic() - start
    assert duration >= 1.0

