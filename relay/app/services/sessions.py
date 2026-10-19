"""Shared rules about when a session code may still be used.

One definition, because the question is asked from three places - the HTTP
lookup the guest page makes, the guest WebSocket, and the operator's own session
list - and three slightly different answers is how a security gap appears.
"""
from datetime import datetime, timezone

from app.models import Session


def is_expired(session: Session, now: datetime | None = None) -> bool:
    """Whether the code has passed its expiry.

    A session whose guest is already in never expires: cutting someone off
    mid-support because a timer ran out would be worse than the risk the timer
    guards against. Expiry governs *joining*, not staying.
    """
    if session.expires_at is None:
        return False
    if session.guest_connected or session.consent_state == "granted":
        return False
    return (now or datetime.now(timezone.utc)) >= session.expires_at


def is_joinable(session: Session | None, now: datetime | None = None) -> bool:
    """Whether a guest may still join with this code."""
    if session is None:
        return False
    if session.state == "ended":
        return False
    return not is_expired(session, now)
