from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    """Liveness plus dependency check. Redis is wired here in P1; it carries
    session pub/sub traffic from P2 onward."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - reported, not raised
        checks["database"] = f"error: {exc.__class__.__name__}"

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - reported, not raised
        checks["redis"] = f"error: {exc.__class__.__name__}"
    finally:
        await redis.aclose()

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
