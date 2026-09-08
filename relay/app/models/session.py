import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SESSION_MODE = ("attended", "unattended")
SESSION_STATE = ("pending", "active", "ended")
CONSENT_STATE = ("pending", "granted", "denied")


class Session(Base):
    """One remote-support session: created by an operator, joined by an endpoint."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    # Operator-facing label. Starts as the join code and can be renamed; the
    # code itself is never editable (Appendix A.5).
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reported by the guest when it joins.
    host_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guest_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guest_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    system_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    monitors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # The endpoint user must allow the session before anything is captured
    # (spec section 9).
    consent_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
