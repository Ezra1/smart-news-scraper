import asyncio
import time
from typing import Optional
from src.logger_config import setup_logging

logger = setup_logging(__name__)

class RateLimiter:
    """
    A unified rate limiter that supports both sync and async operations.
    Can handle both requests per minute and requests per second limits. 
    """
    def __init__(self, 
                 requests_per_minute: Optional[int] = None,
                 requests_per_second: Optional[float] = None) -> None:
        if not (requests_per_minute or requests_per_second):
            raise ValueError("Must specify either requests_per_minute or requests_per_second")
            
        self.requests_per_minute = requests_per_minute
        self.requests_per_second = requests_per_second
        self.request_times = []
        self._last_request_time = 0

    def wait_if_needed(self) -> None:
        """Synchronous rate limiting."""
        current_time = time.time()
        
        if self.requests_per_minute:
            # Clean up old request times
            self.request_times = [t for t in self.request_times if current_time - t < 60]
            
            # Check if we need to wait
            if len(self.request_times) >= self.requests_per_minute:
                wait_time = 60 - (current_time - self.request_times[0])
                if wait_time > 0:
                    logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                    time.sleep(wait_time)

        # Handle per-second rate limiting
        if self.requests_per_second:
            time_since_last = current_time - self._last_request_time
            min_interval = 1.0 / self.requests_per_second
            if time_since_last < min_interval:
                time.sleep(min_interval - time_since_last)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)

    async def wait_if_needed_async(self) -> None:
        """Asynchronous rate limiting."""
        current_time = time.time()
        
        if self.requests_per_minute:
            # Clean up old request times
            self.request_times = [t for t in self.request_times if current_time - t < 60]
            
            # Check if we need to wait
            if len(self.request_times) >= self.requests_per_minute:
                wait_time = 60 - (current_time - self.request_times[0])
                if wait_time > 0:
                    logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)

        # Handle per-second rate limiting
        if self.requests_per_second:
            time_since_last = current_time - self._last_request_time
            min_interval = 1.0 / self.requests_per_second
            if time_since_last < min_interval:
                await asyncio.sleep(min_interval - time_since_last)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)