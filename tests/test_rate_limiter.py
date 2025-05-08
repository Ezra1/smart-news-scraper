import pytest
import asyncio
import time
from src.utils.rate_limiter import RateLimiter

async def test_async_rate_limiting():
    limiter = RateLimiter(requests_per_second=2)  # 2 requests per second
    start_time = time.time()
    
    for _ in range(3):  # Should take at least 1 second
        await limiter.wait_if_needed_async()
    
    duration = time.time() - start_time
    assert duration >= 1.0, "Rate limiting not working as expected"