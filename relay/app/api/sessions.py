import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, current_operator
from app.core.codes import generate_session_code
from app.core.config import settings
from app.db.session import get_db
from app.models import AuditEvent, Device, Operator, Session
from app.schemas.audit import AuditEventOut
from app.schemas.session import (
    SessionCreate,
    SessionHistoryEntry,
    SessionOut,
    SessionUpdate,
)
from app.services import audit
from app.services.hub import hub

router = APIRouter(prefix="/sessions", tags=["sessions"])

SESSION_RENAMED = "session.renamed"


async def _get_or_404(db: AsyncSession, session_id: uuid.UUID) -> Session:
    session = await db.scalar(select(Session).where(Session.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> Session:
    if payload.mode == "unattended":
        if payload.device_id is None:
            raise HTTPException(status_code=400, detail="An unattended session requires a device_id")
        device = await db.scalar(select(Device).where(Device.id == payload.device_id))
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

    # The code is short and human-readable, so a collision is possible; retry.
    for _ in range(5):
        code = generate_session_code(settings.session_code_length)
        session = Session(
            code=code,
            name=payload.name or code,
            mode=payload.mode,
            state="pending",
            operator_id=operator.id,
            device_id=payload.device_id,
        )
        db.add(session)
        try:
            await db.flush()
            break
        except IntegrityError:
            await db.rollback()
    else:
        raise HTTPException(status_code=500, detail="Could not allocate a session code")

    await audit.record(
        db,
        action=audit.SESSION_CREATED,
        actor_id=operator.id,
        actor_label=operator.email,
        target_type="session",
        target_id=str(session.id),
        ip=client_ip(request),
        detail={
            "mode": session.mode,
            "code": session.code,
            "device_id": str(payload.device_id) if payload.device_id else None,
        },
    )
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
    state: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Filter by session name or code"),
    limit: int = Query(default=200, le=500),
) -> list[Session]:
    stmt = select(Session).order_by(Session.created_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(Session.state == state)
    sessions = list((await db.scalars(stmt)).all())

    if q:
        needle = q.strip().lower()
        sessions = [
            s
            for s in sessions
            if needle in s.name.lower()
            or needle in s.code.lower()
            or needle in (s.host_name or "").lower()
        ]

    for session in sessions:
        session.guest_connected = _present(session)
    return sessions


def _present(session: Session) -> bool:
    """A guest counts as joined only once consent is granted and its socket is
    live. Presence alone must never imply the endpoint agreed to share."""
    if session.consent_state != "granted" or session.state == "ended":
        return False
    return hub.guest_online(session.code) or session.guest_connected


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> Session:
    session = await _get_or_404(db, session_id)
    session.guest_connected = _present(session)
    return session


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> Session:
    session = await _get_or_404(db, session_id)
    ip = client_ip(request)

    if payload.name is not None and payload.name != session.name:
        previous = session.name
        session.name = payload.name
        await audit.record(
            db,
            action=SESSION_RENAMED,
            actor_id=operator.id,
            actor_label=operator.email,
            target_type="session",
            target_id=str(session.id),
            ip=ip,
            detail={"from": previous, "to": payload.name},
        )

    if payload.state is not None and payload.state != session.state:
        if session.state == "ended":
            raise HTTPException(status_code=409, detail="Session has already ended")
        previous_state = session.state
        session.state = payload.state
        now = datetime.now(timezone.utc)
        if payload.state == "active" and session.started_at is None:
            session.started_at = now
        if payload.state == "ended":
            session.ended_at = now
            session.guest_connected = False
        await audit.record(
            db,
            action=audit.SESSION_STATE_CHANGED,
            actor_id=operator.id,
            actor_label=operator.email,
            target_type="session",
            target_id=str(session.id),
            ip=ip,
            detail={"from": previous_state, "to": payload.state},
        )

    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> None:
    """Sessions are ended rather than erased, so the audit trail stays whole."""
    session = await _get_or_404(db, session_id)
    if session.state != "ended":
        session.state = "ended"
        session.ended_at = datetime.now(timezone.utc)
        session.guest_connected = False
    await audit.record(
        db,
        action=audit.SESSION_STATE_CHANGED,
        actor_id=operator.id,
        actor_label=operator.email,
        target_type="session",
        target_id=str(session.id),
        ip=client_ip(request),
        detail={"to": "ended", "via": "delete"},
    )
    await db.commit()


@router.get("/{session_id}/history", response_model=list[SessionHistoryEntry])
async def session_history(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> list[SessionHistoryEntry]:
    """Past sessions for the same machine (Appendix A.6)."""
    session = await _get_or_404(db, session_id)

    stmt = select(Session).order_by(Session.created_at.desc()).limit(100)
    if session.device_id is not None:
        stmt = stmt.where(Session.device_id == session.device_id)
    elif session.host_name:
        stmt = stmt.where(Session.host_name == session.host_name)
    else:
        stmt = stmt.where(Session.id == session.id)

    entries: list[SessionHistoryEntry] = []
    for row in (await db.scalars(stmt)).all():
        duration = None
        if row.started_at and row.ended_at:
            duration = int((row.ended_at - row.started_at).total_seconds())
        entries.append(
            SessionHistoryEntry(
                id=row.id,
                name=row.name,
                code=row.code,
                kind=row.mode,
                state=row.state,
                created_at=row.created_at,
                started_at=row.started_at,
                ended_at=row.ended_at,
                duration_seconds=duration,
            )
        )
    return entries


@router.get("/{session_id}/logs", response_model=list[AuditEventOut])
async def session_logs(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> list[AuditEvent]:
    """The server-side audit trail for this session (Appendix A.6)."""
    session = await _get_or_404(db, session_id)
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.target_type == "session", AuditEvent.target_id == str(session.id))
        .order_by(AuditEvent.id.desc())
        .limit(200)
    )
    return list((await db.scalars(stmt)).all())
