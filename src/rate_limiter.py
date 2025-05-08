"""Rate limiting utility for API requests."""

import time
import asyncio
from datetime import datetime
from typing import Optional, Callable, Any

from src.logger_config import setup_logging
logger = setup_logging(__name__)

class RateLimiter:
    """
    A flexible rate limiter for API requests that supports both synchronous and asynchronous usage.
    
    Attributes:
        requests_per_minute (int): Maximum number of requests allowed per minute
        requests_per_second (float): Maximum number of requests allowed per second
        request_times (list): List of timestamps for recent requests
        _last_request_time (float): Timestamp of the last request
    """
    
    def __init__(self, requests_per_minute: int = 60, requests_per_second: Optional[float] = None):
        """
        Initialize the rate limiter.
        
        Args:
            requests_per_minute: Maximum number of requests allowed per minute
            requests_per_second: Maximum number of requests allowed per second (optional)
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_second = requests_per_second or (requests_per_minute / 60.0)
        self.request_times = []
        self._last_request_time = 0
        
    def wait_if_needed(self) -> None:
        """
        Implement rate limiting based on requests per minute and per second.
        Blocks until it's safe to make another request.
        """
        current_time = time.time()
        
        # Clean up old request times (older than 60 seconds)
        self.request_times = [t for t in self.request_times if current_time - t < 60]
        
        # Check if we need to wait for per-minute limit
        if len(self.request_times) >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.request_times[0])
            if wait_time > 0:
                logger.debug(f"Rate limit reached. Waiting {wait_time:.2f} seconds.")
                time.sleep(wait_time)
        
        # Ensure minimum time between requests (per-second limit)
        time_since_last_request = current_time - self._last_request_time
        min_interval = 1.0 / self.requests_per_second
        if time_since_last_request < min_interval:
            time.sleep(min_interval - time_since_last_request)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)
    
    async def async_wait_if_needed(self) -> None:
        """
        Asynchronous version of wait_if_needed.
        Awaits until it's safe to make another request.
        """
        current_time = time.time()
        
        # Clean up old request times (older than 60 seconds)
        self.request_times = [t for t in self.request_times if current_time - t < 60]
        
        # Check if we need to wait for per-minute limit
        if len(self.request_times) >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.request_times[0])
            if wait_time > 0:
                logger.debug(f"Rate limit reached. Waiting {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
        
        # Ensure minimum time between requests (per-second limit)
        time_since_last_request = current_time - self._last_request_time
        min_interval = 1.0 / self.requests_per_second
        if time_since_last_request < min_interval:
            await asyncio.sleep(min_interval - time_since_last_request)
        
        # Update tracking
        self._last_request_time = time.time()
        self.request_times.append(self._last_request_time)
    
    def __call__(self, func: Callable) -> Callable:
        """
        Decorator for rate-limiting a function.
        
        Args:
            func: The function to rate-limit
            
        Returns:
            A wrapped function that respects rate limits
        """
        def wrapper(*args, **kwargs):
            self.wait_if_needed()
            return func(*args, **kwargs)
        return wrapper
    
    def async_decorator(self, func: Callable) -> Callable:
        """
        Decorator for rate-limiting an async function.
        
        Args:
            func: The async function to rate-limit
            
        Returns:
            A wrapped async function that respects rate limits
        """
        async def wrapper(*args, **kwargs):
            await self.async_wait_if_needed()
            return await func(*args, **kwargs)
        return wrapper