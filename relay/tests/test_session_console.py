"""Endpoints the operator console added for Appendix A."""


async def _session(client, headers):
    return (await client.post("/sessions", json={"mode": "attended"}, headers=headers)).json()


async def test_new_session_is_named_after_its_code(client, auth_headers):
    session = await _session(client, auth_headers)
    assert session["name"] == session["code"]
    assert session["guest_connected"] is False
    assert session["host_name"] is None
    assert session["system_info"] == {}
    assert session["monitors"] == []


async def test_rename_leaves_the_join_code_untouched(client, auth_headers):
    session = await _session(client, auth_headers)
    renamed = await client.patch(
        f"/sessions/{session['id']}", json={"name": "Reception Desk"}, headers=auth_headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Reception Desk"
    assert renamed.json()["code"] == session["code"]


async def test_rename_is_audited(client, auth_headers):
    session = await _session(client, auth_headers)
    await client.patch(f"/sessions/{session['id']}", json={"name": "Bench PC"}, headers=auth_headers)

    logs = (await client.get(f"/sessions/{session['id']}/logs", headers=auth_headers)).json()
    renames = [e for e in logs if e["action"] == "session.renamed"]
    assert renames
    assert renames[0]["detail"] == {"from": session["code"], "to": "Bench PC"}


async def test_rename_rejects_an_empty_name(client, auth_headers):
    session = await _session(client, auth_headers)
    response = await client.patch(
        f"/sessions/{session['id']}", json={"name": ""}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_search_matches_name_and_code(client, auth_headers):
    session = await _session(client, auth_headers)
    await client.patch(
        f"/sessions/{session['id']}", json={"name": "Warehouse Terminal"}, headers=auth_headers
    )

    by_name = (await client.get("/sessions?q=warehouse", headers=auth_headers)).json()
    assert [s["id"] for s in by_name] == [session["id"]]

    by_code = (await client.get(f"/sessions?q={session['code']}", headers=auth_headers)).json()
    assert session["id"] in [s["id"] for s in by_code]


async def test_delete_ends_the_session_and_keeps_the_record(client, auth_headers):
    """Sessions are ended, never erased - the audit trail must stay whole."""
    session = await _session(client, auth_headers)
    assert (await client.delete(f"/sessions/{session['id']}", headers=auth_headers)).status_code == 204

    after = await client.get(f"/sessions/{session['id']}", headers=auth_headers)
    assert after.status_code == 200
    assert after.json()["state"] == "ended"
    assert after.json()["ended_at"] is not None


async def test_session_logs_are_scoped_to_that_session(client, auth_headers):
    first = await _session(client, auth_headers)
    second = await _session(client, auth_headers)

    logs = (await client.get(f"/sessions/{first['id']}/logs", headers=auth_headers)).json()
    assert logs
    assert all(e["target_id"] == first["id"] for e in logs)
    assert second["id"] not in [e["target_id"] for e in logs]


async def test_session_history_returns_entries_for_the_machine(client, auth_headers):
    session = await _session(client, auth_headers)
    history = await client.get(f"/sessions/{session['id']}/history", headers=auth_headers)
    assert history.status_code == 200
    rows = history.json()
    assert rows
    assert rows[0]["code"] == session["code"]
    assert rows[0]["kind"] == "attended"


async def test_console_endpoints_reject_anonymous_callers(client, auth_headers):
    session = await _session(client, auth_headers)
    for path in (f"/sessions/{session['id']}/logs", f"/sessions/{session['id']}/history"):
        assert (await client.get(path)).status_code == 401


async def test_presence_requires_consent_even_if_the_row_says_connected(client, auth_headers):
    """The consent gate must not be defeatable by a stale or forged row.

    A session row is put into the state a compromised agent would want -
    guest_connected true - while consent is still pending. The API must still
    report the guest as absent.
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Session as SessionRow

    created = await _session(client, auth_headers)

    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        row.guest_connected = True
        row.consent_state = "pending"
        await db.commit()

    fetched = (await client.get(f"/sessions/{created['id']}", headers=auth_headers)).json()
    assert fetched["consent_state"] == "pending"
    assert fetched["guest_connected"] is False

    listed = (await client.get(f"/sessions?q={created['code']}", headers=auth_headers)).json()
    assert listed[0]["guest_connected"] is False


async def test_presence_is_false_once_a_session_has_ended(client, auth_headers):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Session as SessionRow

    created = await _session(client, auth_headers)
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        row.guest_connected = True
        row.consent_state = "granted"
        await db.commit()

    await client.delete(f"/sessions/{created['id']}", headers=auth_headers)
    fetched = (await client.get(f"/sessions/{created['id']}", headers=auth_headers)).json()
    assert fetched["state"] == "ended"
    assert fetched["guest_connected"] is False
