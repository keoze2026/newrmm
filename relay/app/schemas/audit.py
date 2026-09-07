import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    actor_label: str
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    detail: dict[str, Any]

    model_config = {"from_attributes": True}
