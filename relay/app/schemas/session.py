import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    mode: Literal["attended", "unattended"] = "attended"
    device_id: uuid.UUID | None = None
    name: str | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    mode: str
    state: str
    operator_id: uuid.UUID
    device_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    host_name: str | None
    guest_connected: bool
    guest_joined_at: datetime | None
    guest_last_seen_at: datetime | None
    system_info: dict[str, Any]
    monitors: list[Any]
    agent_version: str | None
    consent_state: str
    consent_at: datetime | None

    model_config = {"from_attributes": True}


class SessionUpdate(BaseModel):
    """Rename a session, or move its state. The join code is never editable."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    state: Literal["active", "ended"] | None = None


class SessionHistoryEntry(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    kind: str
    state: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None


class GuestHello(BaseModel):
    """Sent by the endpoint agent when it joins a session with the code."""

    host_name: str
    system_info: dict[str, Any] = Field(default_factory=dict)
    monitors: list[Any] = Field(default_factory=list)
