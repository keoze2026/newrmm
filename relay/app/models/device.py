import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DEVICE_OS = ("windows", "macos", "linux")
DEVICE_STATUS = ("offline", "online")


class Device(Base):
    """An enrolled endpoint machine. Rows exist in P1; the agent connects in P2."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    os: Mapped[str] = mapped_column(String(16), nullable=False)
    # Per-device enrollment secret; only ever stored hashed (spec section 9).
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline")
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
