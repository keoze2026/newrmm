import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent

# Action names used across the platform. Kept as constants so the console and the
# tests refer to the same strings.
LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILED = "auth.login.failed"
SESSION_CREATED = "session.created"
SESSION_STATE_CHANGED = "session.state_changed"
DEVICE_ENROLLED = "device.enrolled"


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_type: str = "operator",
    actor_id: uuid.UUID | None = None,
    actor_label: str = "",
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one row to the audit trail. Never updates or deletes."""
    event = AuditEvent(
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        detail=detail or {},
    )
    db.add(event)
    await db.flush()
    return event
