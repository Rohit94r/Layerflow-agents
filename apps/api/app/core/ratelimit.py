"""In-process sliding-window rate limiter (single API process; no Redis needed at this scale)."""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False, max(0.0, window_s - (now - q[0]))
            q.append(now)
            if len(self._hits) > 10_000:
                self._gc(now, window_s)
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def _gc(self, now: float, window_s: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > window_s]:
            self._hits.pop(k, None)


limiter = RateLimiter()
