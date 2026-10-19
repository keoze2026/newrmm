"""Session codes expire (security review finding).

A code is a credential. One shared over chat months ago should not still join.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Session as SessionRow
from app.services.sessions import is_expired, is_joinable


async def _session(client, headers):
    return (await client.post("/sessions", json={"mode": "attended"}, headers=headers)).json()


async def _age(session_id: str, minutes: int) -> None:
    """Move a session's expiry into the past."""
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == session_id))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await db.commit()


async def test_a_new_session_has_an_expiry(client, auth_headers):
    created = await _session(client, auth_headers)
    assert created["expires_at"] is not None
    expires = datetime.fromisoformat(created["expires_at"])
    assert expires > datetime.now(timezone.utc)


async def test_the_expiry_is_recorded_on_the_audit_trail(client, auth_headers):
    created = await _session(client, auth_headers)
    logs = (await client.get(f"/sessions/{created['id']}/logs", headers=auth_headers)).json()
    made = [e for e in logs if e["action"] == "session.created"]
    assert made and made[0]["detail"].get("expires_at")


async def test_a_fresh_code_is_joinable(client, auth_headers):
    created = await _session(client, auth_headers)
    assert (await client.get(f"/connector/session/{created['code']}")).status_code == 200


async def test_an_expired_code_stops_joining(client, auth_headers):
    created = await _session(client, auth_headers)
    await _age(created["id"], minutes=5)
    response = await client.get(f"/connector/session/{created['code']}")
    assert response.status_code == 404


async def test_an_expired_code_looks_the_same_as_an_unknown_one(client, auth_headers):
    """Whether a code was ever real is not the caller's business."""
    created = await _session(client, auth_headers)
    await _age(created["id"], minutes=5)

    expired = await client.get(f"/connector/session/{created['code']}")
    unknown = await client.get("/connector/session/ZZZZZZZZ")
    assert expired.status_code == unknown.status_code == 404
    assert expired.json() == unknown.json()


async def test_an_expired_session_reports_no_guest_to_the_operator(client, auth_headers):
    created = await _session(client, auth_headers)
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        row.guest_connected = True
        row.consent_state = "pending"
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

    fetched = (await client.get(f"/sessions/{created['id']}", headers=auth_headers)).json()
    assert fetched["guest_connected"] is False


async def test_a_live_session_never_expires_mid_support():
    """Cutting someone off because a timer ran out would be worse than the risk
    the timer guards against. Expiry governs joining, not staying."""
    past = datetime.now(timezone.utc) - timedelta(hours=2)

    joined = SessionRow(
        code="LIVE1234", name="live", mode="attended", state="active",
        expires_at=past, guest_connected=True, consent_state="granted",
    )
    assert is_expired(joined) is False

    consented = SessionRow(
        code="LIVE5678", name="live", mode="attended", state="active",
        expires_at=past, guest_connected=False, consent_state="granted",
    )
    assert is_expired(consented) is False

    waiting = SessionRow(
        code="WAIT1234", name="waiting", mode="attended", state="pending",
        expires_at=past, guest_connected=False, consent_state="pending",
    )
    assert is_expired(waiting) is True


def test_a_session_without_an_expiry_is_not_treated_as_expired():
    """Rows that predate the migration must not stop working."""
    legacy = SessionRow(
        code="OLD12345", name="old", mode="attended", state="pending",
        expires_at=None, guest_connected=False, consent_state="pending",
    )
    assert is_expired(legacy) is False
    assert is_joinable(legacy) is True


def test_an_ended_session_is_never_joinable():
    ended = SessionRow(
        code="DONE1234", name="done", mode="attended", state="ended",
        expires_at=None, guest_connected=False, consent_state="granted",
    )
    assert is_joinable(ended) is False
    assert is_joinable(None) is False
