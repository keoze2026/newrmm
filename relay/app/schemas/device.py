import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
