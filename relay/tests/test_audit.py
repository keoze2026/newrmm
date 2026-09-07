import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal
from app.services import audit


async def _actions(client, headers, action):
    response = await client.get(f"/audit?action={action}", headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_successful_login_is_audited(client, auth_headers):
    events = await _actions(client, auth_headers, audit.LOGIN_SUCCESS)
    assert events
    assert events[0]["actor_type"] == "operator"
    assert events[0]["actor_label"] == "tester@example.com"


async def test_failed_login_is_audited(client, auth_headers):
    await client.post(
        "/auth/login", json={"email": "tester@example.com", "password": "wrong-on-purpose"}
    )
    events = await _actions(client, auth_headers, audit.LOGIN_FAILED)
    assert events
    assert events[0]["actor_type"] == "anonymous"
    assert events[0]["detail"]["reason"] == "invalid_credentials"


async def test_session_creation_is_audited(client, auth_headers):
    session = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()

    events = await _actions(client, auth_headers, audit.SESSION_CREATED)
    match = [e for e in events if e["target_id"] == session["id"]]
    assert match, "no audit event recorded for the created session"
    assert match[0]["detail"]["code"] == session["code"]


async def test_session_state_change_is_audited(client, auth_headers):
    session = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    await client.patch(
        f"/sessions/{session['id']}", json={"state": "active"}, headers=auth_headers
    )

    events = await _actions(client, auth_headers, audit.SESSION_STATE_CHANGED)
    match = [e for e in events if e["target_id"] == session["id"]]
    assert match
    assert match[0]["detail"] == {"from": "pending", "to": "active"}


async def test_audit_log_is_append_only(client, auth_headers):
    """The database itself must reject UPDATE and DELETE on the audit trail."""
    async with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE audit_events SET action = 'tampered'"))
        await db.rollback()

        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM audit_events"))
        await db.rollback()


async def test_audit_api_exposes_no_write_routes(client, auth_headers):
    assert (await client.post("/audit", json={}, headers=auth_headers)).status_code == 405
    assert (await client.delete("/audit", headers=auth_headers)).status_code == 405
