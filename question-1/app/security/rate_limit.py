from __future__ import annotations

from collections import deque
import logging
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status


WINDOW_SECONDS = 60.0
logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: float = WINDOW_SECONDS) -> None:
        self._limit = max(1, limit)
        self._window_seconds = window_seconds
        self._clock = monotonic
        self._lock = Lock()
        self._hits_by_key: dict[str, deque[float]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window_seconds

        with self._lock:
            hits = self._hits_by_key.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self._limit:
                return False

            hits.append(now)
            return True


def enforce_v3_chat_rate_limit(request: Request) -> None:
    limiter: SlidingWindowRateLimiter = request.app.state.v3_chat_rate_limiter
    client_ip = _client_ip(request)
    if limiter.allow(client_ip):
        return

    logger.warning(
        "rate_limit_exceeded",
        extra={
            "event": "rate_limit_exceeded",
            "path": request.url.path,
            "client_ip": client_ip,
            "limit": limiter.limit,
            "window_seconds": limiter.window_seconds,
        },
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="rate limit exceeded",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"
