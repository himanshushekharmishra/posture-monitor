"""In-memory sliding-window rate limiter (single server process).  Pure."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class RateLimiter:
    """Allows at most `limit` hits per `window` seconds for each key."""

    def __init__(self, limit: int, window: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        return q

    def allow(self, key: str) -> bool:
        """Record a hit and say whether it's within the limit."""
        with self._lock:
            now = self._clock()
            q = self._trim(key, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """Seconds until the next hit would be allowed (0 if allowed now)."""
        with self._lock:
            now = self._clock()
            q = self._trim(key, now)
            if len(q) < self.limit:
                return 0
            return max(1, int(q[0] + self.window - now) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
