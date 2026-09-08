from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, auth, connector, devices, health, sessions, ws
from app.core.config import settings
from app.core.logging_setup import RequestLogMiddleware
from app.core.logging_setup import configure as configure_logging

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
