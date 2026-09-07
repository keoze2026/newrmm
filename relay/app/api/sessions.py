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
from app.models import Device, Operator, Session
from app.schemas.session import SessionCreate, SessionOut, SessionStateUpdate
from app.services import audit

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
        session = Session(
            code=generate_session_code(settings.session_code_length),
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
        detail={"mode": session.mode, "code": session.code, "device_id": str(payload.device_id) if payload.device_id else None},
    )
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
    state: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[Session]:
    stmt = select(Session).order_by(Session.created_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(Session.state == state)
    return list((await db.scalars(stmt)).all())


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> Session:
    session = await db.scalar(select(Session).where(Session.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session_state(
    session_id: uuid.UUID,
    payload: SessionStateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> Session:
    session = await db.scalar(select(Session).where(Session.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state == "ended":
        raise HTTPException(status_code=409, detail="Session has already ended")

    previous = session.state
    session.state = payload.state
    now = datetime.now(timezone.utc)
    if payload.state == "active" and session.started_at is None:
        session.started_at = now
    if payload.state == "ended":
        session.ended_at = now

    await audit.record(
        db,
        action=audit.SESSION_STATE_CHANGED,
        actor_id=operator.id,
        actor_label=operator.email,
        target_type="session",
        target_id=str(session.id),
        ip=client_ip(request),
        detail={"from": previous, "to": payload.state},
    )
    await db.commit()
    await db.refresh(session)
    return session
