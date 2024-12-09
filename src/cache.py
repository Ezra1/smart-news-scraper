from functools import lru_cache
from datetime import datetime, timedelta
import hashlib
from typing import Any, Optional

class QueryCache:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self._cache = {}
    
    def _make_key(self, query: str, params: tuple) -> str:
        return hashlib.md5(f"{query}{str(params)}".encode()).hexdigest()
    
    def get(self, query: str, params: tuple) -> Optional[Any]:
        key = self._make_key(query, params)
        if key in self._cache:
            result, timestamp = self._cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return result
            del self._cache[key]
        return None
    
    def set(self, query: str, params: tuple, result: Any) -> None:
        key = self._make_key(query, params)
        self._cache[key] = (result, datetime.now())