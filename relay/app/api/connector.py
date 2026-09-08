"""Serving the connector to the person being helped.

Specification section 4: "Attended sessions | User receives a short code + link,
runs a connector, and is instantly connected to the operator."

The guest opens the join link, downloads the connector for their platform and
runs it. These routes are deliberately unauthenticated: the guest has no account
and never will. Knowing a valid session code is the credential, exactly as it is
for the agent's own WebSocket, and the code is short-lived and single-use in
practice because a session accepts one guest at a time.
"""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip
from app.db.session import get_db
from app.models import Session
from app.services import audit

router = APIRouter(prefix="/connector", tags=["connector"])

CONNECTOR_DOWNLOADED = "connector.downloaded"

# Where agent/build.py leaves its output. Mounted into the relay container in
# the compose stack; present on disk in a local checkout.
BUILD_DIR = Path(__file__).resolve().parents[3] / "agent" / "dist"

# Each build.py run leaves a platform-suffixed copy, so all three can sit in
# one directory when CI collects them. The plain names are accepted too, which
# is what a local build produces.
PLATFORMS = {
    "windows": {
        "files": ["rmm-agent-windows.exe", "rmm-agent.exe"],
        "label": "Windows",
        "hint": "Windows 10 2004+ / 11",
    },
    "macos": {
        "files": ["rmm-agent-macos", "rmm-agent-macos.zip"],
        "label": "macOS",
        "hint": "macOS 12 or newer",
    },
    "linux": {
        "files": ["rmm-agent-linux", "rmm-agent"],
        "label": "Linux",
        "hint": "X11 desktops",
    },
}


def _artefact(platform: str) -> Path | None:
    entry = PLATFORMS.get(platform)
    if entry is None:
        return None
    for name in entry["files"]:
        path = BUILD_DIR / name
        if path.is_file():
            return path
    return None


def _digest(path: Path) -> str:
    """So the guest can check what they downloaded is what we built."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


@router.get("")
async def list_connectors() -> dict:
    """Which connector builds this relay can hand out."""
    builds = []
    for platform, entry in PLATFORMS.items():
        path = _artefact(platform)
        builds.append(
            {
                "platform": platform,
                "label": entry["label"],
                "requirements": entry["hint"],
                "available": path is not None,
                "size": path.stat().st_size if path else None,
                "sha256": _digest(path) if path else None,
            }
        )
    return {"builds": builds}


@router.get("/session/{code}")
async def session_for_code(code: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Confirm a code before the guest downloads anything.

    Returns only what a guest needs to see - never the operator, the device or
    anything about other sessions.
    """
    session = await db.scalar(select(Session).where(Session.code == code.upper()))
    if session is None or session.state == "ended":
        raise HTTPException(status_code=404, detail="That session code is not valid")
    return {
        "code": session.code,
        "name": session.name,
        "waiting": session.consent_state != "granted",
        "connected": session.guest_connected,
    }


@router.get("/{platform}")
async def download_connector(
    platform: str,
    request: Request,
    code: str = "",
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Hand over the connector for one platform."""
    entry = PLATFORMS.get(platform)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No connector for {platform!r}")

    path = _artefact(platform)
    if path is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"The {entry['label']} connector has not been built on this server. "
                "Build it with agent/build.py on a machine of that platform and "
                "place it in agent/dist/."
            ),
        )

    # Downloads are part of the session's story, so they belong in the trail.
    if code:
        session = await db.scalar(select(Session).where(Session.code == code.upper()))
        if session is not None:
            await audit.record(
                db,
                action=CONNECTOR_DOWNLOADED,
                actor_type="guest",
                actor_label=code.upper(),
                target_type="session",
                target_id=str(session.id),
                ip=client_ip(request),
                detail={"platform": platform},
            )
            await db.commit()

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
        headers={"X-Connector-SHA256": _digest(path)},
    )
