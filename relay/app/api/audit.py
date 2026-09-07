from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_operator
from app.db.session import get_db
from app.models import AuditEvent, Operator
from app.schemas.audit import AuditEventOut

# Read-only by design: the audit trail is append-only (spec section 9), so this
# router exposes no create, update or delete route.
router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
async def list_audit_events(
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
    action: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    return list((await db.scalars(stmt)).all())
