from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api import audit, auth, connector, devices, health, sessions, ws
from app.core.config import settings
from app.core.logging_setup import RequestLogMiddleware
from app.core.logging_setup import configure as configure_logging
from app.db.session import SessionLocal
from app.models import Device, Session

configure_logging(settings.log_dir, settings.log_level)

# Found by the Phase 6 security review: the JWT secret has a placeholder
# default, and anyone holding it can mint operator tokens. Refuse to start with
# it outside development rather than run quietly insecure.
if settings.environment != "development" and settings.jwt_secret in (
    "change-me-in-production",
    "dev-only-secret-change-in-production",
):
    raise RuntimeError(
        "JWT_SECRET is still the placeholder. Set it to a long random value "
        "before running outside development: openssl rand -hex 32"
    )

app = FastAPI(
    title="Remote Desktop & Support Platform - Relay",
    version="0.1.0",
    description="Operator auth, session model, audit log and the session transport.",
)

app.add_middleware(RequestLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(devices.router)
app.include_router(audit.router)
app.include_router(connector.router)
app.include_router(ws.router)


@app.on_event("startup")
async def reset_stale_presence() -> None:
    """A fresh process has no live socket anywhere yet - `hub` always starts
    empty on restart - so any row still claiming a guest/device is connected
    is stale, left by a connection whose disconnect cleanup never ran because
    the process exited (e.g. mid-restart for a deploy) before its `finally`
    block could. `_present()`'s `session.guest_connected` fallback exists for
    a guest attached to a *different* relay instance under Redis fan-out,
    which this single-worker deployment does not use - here it has no way to
    ever self-correct otherwise, unlike a device's own 90s freshness window.
    """
    async with SessionLocal() as db:
        await db.execute(update(Session).where(Session.guest_connected.is_(True)).values(guest_connected=False))
        await db.execute(update(Device).where(Device.status == "online").values(status="offline"))
        await db.commit()
