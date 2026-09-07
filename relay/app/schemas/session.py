import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SessionCreate(BaseModel):
    mode: Literal["attended", "unattended"] = "attended"
    device_id: uuid.UUID | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    code: str
    mode: str
    state: str
    operator_id: uuid.UUID
    device_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class SessionStateUpdate(BaseModel):
    state: Literal["active", "ended"]
