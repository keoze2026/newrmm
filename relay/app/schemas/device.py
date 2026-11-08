import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    name: str
    os: Literal["windows", "macos", "linux"]


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    os: str
    status: str
    enrolled_at: datetime
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class DeviceEnrolled(DeviceOut):
    # The plaintext enrollment secret is returned exactly once, at creation.
    enrollment_secret: str


class EnrolByCode(BaseModel):
    """Sent by an agent whose user chose "always allow" in the consent window."""

    code: str = Field(min_length=4, max_length=16)
    name: str = Field(min_length=1, max_length=255)
    os: Literal["windows", "macos", "linux"]
    # The secret the relay gave this computer when it joined the session.
    # Required once the session is bound to a computer, so only the computer
    # actually in the session can enrol itself.
    guest_token: str | None = Field(default=None, max_length=128)


class EnrolledByCode(BaseModel):
    device_id: str
    secret: str

