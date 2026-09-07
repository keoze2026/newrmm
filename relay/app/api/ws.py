"""Session transport: the operator console and the endpoint guest meet here.

Guest  -> relay : binary JPEG frames, plus JSON status messages.
Operator -> relay: JSON control messages (mouse, keyboard, monitor, blank).
The relay forwards between the two halves of a session and keeps the database
in step with who is connected.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import Operator, Session
from app.services import audit
from app.services.hub import hub

router = APIRouter(tags=["session-transport"])

GUEST_JOINED = "session.guest_joined"
GUEST_LEFT = "session.guest_left"
OPERATOR_ATTACHED = "session.operator_attached"


async def _load_session(code: str) -> Session | None:
    async with SessionLocal() as db:
        return await db.scalar(select(Session).where(Session.code == code.upper()))


@router.websocket("/ws/guest/{code}")
async def guest_socket(websocket: WebSocket, code: str) -> None:
    """The endpoint agent joins with the session code the user was given."""
    code = code.upper()
    session = await _load_session(code)
    if session is None or session.state == "ended":
        await websocket.close(code=4404, reason="Unknown or ended session")
        return

    await websocket.accept()
    channel = hub.channel(code)
    if channel.guest is not None:
        await websocket.close(code=4409, reason="A guest is already connected")
        return
    channel.guest = websocket

    try:
        hello = await websocket.receive_json()
        async with SessionLocal() as db:
            live = await db.scalar(select(Session).where(Session.code == code))
            if live is None:
                await websocket.close(code=4404)
                return
            live.host_name = str(hello.get("host_name", "unknown"))[:255]
            live.system_info = hello.get("system_info", {}) or {}
            live.monitors = hello.get("monitors", []) or []
            live.guest_connected = True
            live.guest_joined_at = datetime.now(timezone.utc)
            live.guest_last_seen_at = live.guest_joined_at
            if live.state == "pending":
                live.state = "active"
                live.started_at = live.guest_joined_at
            await audit.record(
                db,
                action=GUEST_JOINED,
                actor_type="guest",
                actor_label=live.host_name or "guest",
                target_type="session",
                target_id=str(live.id),
                detail={"code": code, "os": (live.system_info or {}).get("os")},
            )
            await db.commit()
            snapshot = {
                "host_name": live.host_name,
                "system_info": live.system_info,
                "monitors": live.monitors,
            }

        await hub.to_operator_json(code, {"type": "guest_joined", **snapshot})

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (payload := message.get("bytes")) is not None:
                await hub.to_operator_bytes(code, payload)
            elif (text := message.get("text")) is not None:
                await hub.to_operator_json(code, {"type": "guest_message", "raw": text})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        channel.guest = None
        hub.drop(code)
        async with SessionLocal() as db:
            live = await db.scalar(select(Session).where(Session.code == code))
            if live is not None:
                live.guest_connected = False
                live.guest_last_seen_at = datetime.now(timezone.utc)
                await audit.record(
                    db,
                    action=GUEST_LEFT,
                    actor_type="guest",
                    actor_label=live.host_name or "guest",
                    target_type="session",
                    target_id=str(live.id),
                    detail={"code": code},
                )
                await db.commit()
        await hub.to_operator_json(code, {"type": "guest_left"})


@router.websocket("/ws/operator/{code}")
async def operator_socket(websocket: WebSocket, code: str, token: str = "") -> None:
    """The console attaches here to receive frames and send input.

    The token travels as a query parameter because a browser cannot set headers
    on a WebSocket handshake.
    """
    code = code.upper()
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=4401, reason="Not authenticated")
        return

    async with SessionLocal() as db:
        try:
            operator = await db.scalar(
                select(Operator).where(Operator.id == uuid.UUID(payload["sub"]))
            )
        except ValueError:
            operator = None
        if operator is None or not operator.is_active:
            await websocket.close(code=4401, reason="Not authenticated")
            return
        session = await db.scalar(select(Session).where(Session.code == code))
        if session is None or session.state == "ended":
            await websocket.close(code=4404, reason="Unknown or ended session")
            return
        await audit.record(
            db,
            action=OPERATOR_ATTACHED,
            actor_id=operator.id,
            actor_label=operator.email,
            target_type="session",
            target_id=str(session.id),
            detail={"code": code},
        )
        await db.commit()
        guest_snapshot = {
            "host_name": session.host_name,
            "system_info": session.system_info,
            "monitors": session.monitors,
        }

    await websocket.accept()
    channel = hub.channel(code)
    channel.operator = websocket

    await websocket.send_json(
        {
            "type": "attached",
            "guest_connected": hub.guest_online(code),
            **guest_snapshot,
        }
    )

    try:
        while True:
            message = await websocket.receive_json()
            await hub.to_guest_json(code, message)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        channel.operator = None
        hub.drop(code)
