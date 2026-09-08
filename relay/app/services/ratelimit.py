"""Rate limiting for the endpoints an unauthenticated caller can reach.

Found by the Phase 6 security review: nothing throttled anything. Three routes
are reachable without credentials and each is worth guessing at -

  POST /auth/login              operator passwords
  GET  /connector/session/{code}  whether a session code is valid
  WS   /ws/guest/{code}         joining a session with only its code

A session code is 8 characters from a 31-character alphabet, about 2^40
combinations, which is only meaningful while guessing is slow. This makes it
slow.

Counters live in Redis so a limit applies across every relay instance, and fall
back to memory when Redis is unavailable - a single instance is still protected,
which is better than failing open entirely.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import settings

log = logging.getLogger(__name__)

_redis: Redis | None = None
_redis_failed = False

# Fallback when Redis is unreachable: caller -> times of recent attempts.
_memory: dict[str, deque] = defaultdict(deque)


async def _client() -> Redis | None:
    global _redis, _redis_failed
    if _redis_failed:
        return None
    if _redis is None:
        try:
            _redis = Redis.from_url(settings.redis_url)
            await _redis.ping()
        except Exception as exc:
            log.warning("rate limiting falls back to memory: %s", exc)
            _redis_failed = True
            _redis = None
    return _redis


def caller(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def hit(key: str, limit: int, window: int) -> tuple[bool, int]:
    """Record an attempt. Returns (allowed, attempts so far in the window)."""
    client = await _client()

    if client is not None:
        try:
            bucket = f"rmm:rate:{key}:{int(time.time()) // window}"
            count = await client.incr(bucket)
            if count == 1:
                await client.expire(bucket, window * 2)
            return count <= limit, int(count)
        except Exception as exc:
            log.debug("rate limit check failed, allowing: %s", exc)
            return True, 0

    now = time.monotonic()
    attempts = _memory[key]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    attempts.append(now)
    # Keep the fallback from growing without bound on a busy relay.
    if len(_memory) > 10_000:
        _memory.clear()
    return len(attempts) <= limit, len(attempts)


async def enforce(request: Request, bucket: str, limit: int, window: int) -> None:
    """Raise 429 when a caller has exceeded the limit."""
    key = f"{bucket}:{caller(request)}"
    allowed, count = await hit(key, limit, window)
    if not allowed:
        log.warning(
            "rate limit hit: %s from %s (%d attempts in %ds)",
            bucket, caller(request), count, window,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Wait a minute and try again.",
            headers={"Retry-After": str(window)},
        )


async def allowed(identifier: str, bucket: str, limit: int, window: int) -> bool:
    """Non-raising form, for WebSocket handlers which cannot return a 429."""
    ok, _ = await hit(f"{bucket}:{identifier}", limit, window)
    return ok
