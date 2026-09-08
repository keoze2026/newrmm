"""Session transport: the operator console and the endpoint agent meet here.

Agent  -> relay : a JSON hello, then a consent decision, then binary JPEG frames.
Operator -> relay: JSON control messages (mouse, keyboard, monitor, blank).

Nothing is relayed to the operator until the endpoint user has granted consent
(spec section 9). The relay drops any frame that arrives before that, so a
misbehaving or modified agent still cannot stream without a decision on record.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_access_token, verify_secret
from app.db.session import SessionLocal
from app.models import Device, Operator, Session
from app.services import audit
from app.services.hub import hub

router = APIRouter(tags=["session-transport"])

GUEST_ATTACHED = "session.guest_attached"
GUEST_JOINED = "session.guest_joined"
GUEST_LEFT = "session.guest_left"
CONSENT_GRANTED = "session.consent_granted"
CONSENT_DENIED = "session.consent_denied"
OPERATOR_ATTACHED = "session.operator_attached"
DEVICE_ONLINE = "device.online"
DEVICE_OFFLINE = "device.offline"


async def _authenticate_device(device_id: str, secret: str) -> Device | None:
    """Unattended endpoints present the per-device secret issued at enrolment."""
    if not device_id or not secret:
        return None
    try:
        identifier = uuid.UUID(device_id)
    except ValueError:
        return None
    async with SessionLocal() as db:
        device = await db.scalar(select(Device).where(Device.id == identifier))
        if device is None or not verify_secret(secret, device.secret_hash):
            return None
        return device


@router.websocket("/ws/guest/{code}")
async def guest_socket(
    websocket: WebSocket,
    code: str,
    device_id: str = "",
    secret: str = "",
) -> None:
    """The endpoint agent joins with the session code the user was given.

    An unattended endpoint additionally presents its device credentials; an
    attended one joins with the code alone, which is what the user was told to
    type in.
    """
    code = code.upper()
    async with SessionLocal() as db:
        session = await db.scalar(select(Session).where(Session.code == code))
        if session is None or session.state == "ended":
            await websocket.close(code=4404, reason="Unknown or ended session")
            return
        needs_device = session.mode == "unattended"
        expected_device_id = str(session.device_id) if session.device_id else None

    if needs_device:
        device = await _authenticate_device(device_id, secret)
        if device is None or (expected_device_id and str(device.id) != expected_device_id):
            await websocket.close(code=4401, reason="Device authentication failed")
            return

    await websocket.accept()
    channel = hub.channel(code)
    if channel.guest is not None:
        await websocket.close(code=4409, reason="A guest is already connected")
        return
    channel.guest = websocket

    consented = False
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
            live.agent_version = str(hello.get("agent_version", ""))[:32] or None
            live.guest_last_seen_at = datetime.now(timezone.utc)
            live.consent_state = "pending"
            await audit.record(
                db,
                action=GUEST_ATTACHED,
                actor_type="guest",
                actor_label=live.host_name or "guest",
                target_type="session",
                target_id=str(live.id),
                detail={
                    "code": code,
                    "os": (live.system_info or {}).get("os"),
                    "agent_version": live.agent_version,
                },
            )
            await db.commit()
            snapshot = {
                "host_name": live.host_name,
                "system_info": live.system_info,
                "monitors": live.monitors,
            }

        # The operator sees the endpoint attach, but no screen until consent.
        await hub.to_operator_json(
            code, {"type": "guest_attached", "consent": "pending", **snapshot}
        )

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if (text := message.get("text")) is not None:
                import json

                try:
                    payload = json.loads(text)
                except ValueError:
                    continue

                if payload.get("type") == "consent":
                    granted = bool(payload.get("granted"))
                    consented = granted
                    now = datetime.now(timezone.utc)
                    async with SessionLocal() as db:
                        live = await db.scalar(select(Session).where(Session.code == code))
                        if live is not None:
                            live.consent_state = "granted" if granted else "denied"
                            live.consent_at = now
                            live.guest_connected = granted
                            if granted:
                                live.guest_joined_at = now
                                if live.state == "pending":
                                    live.state = "active"
                                    live.started_at = now
                            await audit.record(
                                db,
                                action=CONSENT_GRANTED if granted else CONSENT_DENIED,
                                actor_type="guest",
                                actor_label=live.host_name or "guest",
                                target_type="session",
                                target_id=str(live.id),
                                detail={"code": code, "by": payload.get("by", "endpoint user")},
                            )
                            if granted:
                                await audit.record(
                                    db,
                                    action=GUEST_JOINED,
                                    actor_type="guest",
                                    actor_label=live.host_name or "guest",
                                    target_type="session",
                                    target_id=str(live.id),
                                    detail={"code": code},
                                )
                            await db.commit()

                    if granted:
                        await hub.to_operator_json(code, {"type": "guest_joined", **snapshot})
                    else:
                        await hub.to_operator_json(code, {"type": "consent_denied"})
                        await websocket.close(code=4403, reason="Consent denied")
                        break
                elif consented:
                    # Terminal output, file chunks and clipboard replies travel
                    # as JSON; forward them verbatim, but only once the session
                    # is consented.
                    await hub.to_operator_json(code, payload)

            elif (payload_bytes := message.get("bytes")) is not None:
                # Defence in depth: frames before consent are discarded.
                if consented:
                    await hub.to_operator_bytes(code, payload_bytes)

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
                    detail={"code": code, "consented": consented},
                )
                await db.commit()
        await hub.to_operator_json(code, {"type": "guest_left"})


@router.websocket("/ws/device/{device_id}")
async def device_socket(websocket: WebSocket, device_id: str, secret: str = "") -> None:
    """Unattended presence: an enrolled endpoint stays reachable here.

    The agent holds this socket open so the console can see the device online.
    Starting a session still goes through /ws/guest with the session code.
    """
    device = await _authenticate_device(device_id, secret)
    if device is None:
        await websocket.close(code=4401, reason="Device authentication failed")
        return

    await websocket.accept()
    async with SessionLocal() as db:
        live = await db.scalar(select(Device).where(Device.id == device.id))
        if live is not None:
            live.status = "online"
            live.last_seen_at = datetime.now(timezone.utc)
            await audit.record(
                db,
                action=DEVICE_ONLINE,
                actor_type="device",
                actor_label=live.name,
                target_type="device",
                target_id=str(live.id),
            )
            await db.commit()

    try:
        while True:
            await websocket.receive_text()
            async with SessionLocal() as db:
                live = await db.scalar(select(Device).where(Device.id == device.id))
                if live is not None:
                    live.last_seen_at = datetime.now(timezone.utc)
                    await db.commit()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with SessionLocal() as db:
            live = await db.scalar(select(Device).where(Device.id == device.id))
            if live is not None:
                live.status = "offline"
                live.last_seen_at = datetime.now(timezone.utc)
                await audit.record(
                    db,
                    action=DEVICE_OFFLINE,
                    actor_type="device",
                    actor_label=live.name,
                    target_type="device",
                    target_id=str(live.id),
                )
                await db.commit()


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
            "consent": session.consent_state,
        }

    await websocket.accept()
    channel = hub.channel(code)
    channel.operator = websocket

    await websocket.send_json(
        {
            "type": "attached",
            "guest_connected": hub.guest_online(code) and guest_snapshot["consent"] == "granted",
            **guest_snapshot,
        }
    )

    # The endpoint streams changed regions, so a freshly attached operator has
    # no picture to patch. Ask for a whole frame first.
    await hub.to_guest_json(code, {"type": "keyframe"})

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
