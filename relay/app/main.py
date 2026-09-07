from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, auth, devices, health, sessions
from app.core.config import settings

app = FastAPI(
    title="Remote Desktop & Support Platform - Relay",
    version="0.1.0",
    description="Phase 1: authentication, session model and audit log.",
)

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
