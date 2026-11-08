"""Shared rules about when a session code may still be used.

One definition, because the question is asked from three places - the HTTP
lookup the guest page makes, the guest WebSocket, and the operator's own session
list - and three slightly different answers is how a security gap appears.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models import Session


def is_expired(session: Session, now: datetime | None = None) -> bool:
    """Whether the code has passed its expiry.

    A session whose guest is in right now never expires: cutting someone off
    mid-support because a timer ran out would be worse than the risk the timer
    guards against. Expiry governs *joining*, not staying.

    A session that was consented and whose guest has since gone stays
    rejoinable for `session_rejoin_minutes` after the guest was last seen (a
    reboot, a dropped link), then expires like any other code. It used to stay
    joinable for ever.

    A standing session (an enrolled device) has no expiry at all; it is
    protected by the device's own secret instead.
    """
    if session.expires_at is None:
        return False
    if session.guest_connected:
        return False
    now = now or datetime.now(timezone.utc)
    if session.consent_state == "granted":
        last = session.guest_last_seen_at or session.consent_at or session.expires_at
        return now >= last + timedelta(minutes=settings.session_rejoin_minutes)
    return now >= session.expires_at


def new_guest_token() -> tuple[str, str]:
    """A fresh guest secret and the hash that is stored for it."""
    token = secrets.token_urlsafe(32)
    return token, hash_guest_token(token)


def hash_guest_token(token: str) -> str:
    # A 256-bit random value needs no slow hash; SHA-256 keeps the check cheap
    # on the single relay worker.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def guest_token_matches(session: Session, presented: str | None) -> bool:
    """Whether `presented` is the secret of the computer bound to `session`.

    A session nobody has bound yet (no hash) matches anything: agents older
    than this check never receive a secret, and must keep working.
    """
    if not session.guest_token_hash:
        return True
    if not presented:
        return False
    return hmac.compare_digest(hash_guest_token(presented), session.guest_token_hash)


def is_joinable(session: Session | None, now: datetime | None = None) -> bool:
    """Whether a guest may still join with this code."""
    if session is None:
        return False
    if session.state == "ended":
        return False
    return not is_expired(session, now)
