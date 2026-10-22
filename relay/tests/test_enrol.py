"""Always-on devices: a person who chooses "always allow" enrols their computer.

The agent asks the relay to turn the live, consented session into a standing
one for this device. Only a session whose person already agreed can be turned
into one, and afterwards it never expires and belongs to the device.
"""
from sqlalchemy import select

from app.core.security import verify_secret
from app.db.session import SessionLocal
from app.models import Device, Session as SessionRow


async def _live_session(client, headers, consent="granted", connected=True):
    created = (await client.post("/sessions", json={"mode": "attended"}, headers=headers)).json()
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        row.consent_state = consent
        row.guest_connected = connected
        row.host_name = "laptop"
        await db.commit()
    return created


def _body(code):
    return {"code": code, "name": "Hans laptop", "os": "linux"}


async def test_a_consented_live_session_becomes_a_standing_one(client, auth_headers):
    created = await _live_session(client, auth_headers)
    response = await client.post("/connector/enrol", json=_body(created["code"]))
    assert response.status_code == 201
    enrolled = response.json()

    async with SessionLocal() as db:
        session = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        device = await db.scalar(select(Device).where(Device.id == enrolled["device_id"]))
    assert session.mode == "unattended"
    assert str(session.device_id) == enrolled["device_id"]
    assert session.expires_at is None, "a standing session must not expire"
    assert device is not None and device.os == "linux"
    assert verify_secret(enrolled["secret"], device.secret_hash)
    assert enrolled["secret"] != device.secret_hash, "the secret is only ever stored hashed"


async def test_a_session_nobody_agreed_to_cannot_be_enrolled(client, auth_headers):
    created = await _live_session(client, auth_headers, consent="pending")
    response = await client.post("/connector/enrol", json=_body(created["code"]))
    assert response.status_code == 409


async def test_a_session_with_no_one_present_cannot_be_enrolled(client, auth_headers):
    created = await _live_session(client, auth_headers, connected=False)
    response = await client.post("/connector/enrol", json=_body(created["code"]))
    assert response.status_code == 409


async def test_an_unknown_code_cannot_be_enrolled(client):
    response = await client.post("/connector/enrol", json=_body("NOPE1234"))
    assert response.status_code == 409


async def test_a_standing_session_cannot_be_enrolled_twice(client, auth_headers):
    created = await _live_session(client, auth_headers)
    assert (await client.post("/connector/enrol", json=_body(created["code"]))).status_code == 201
    assert (await client.post("/connector/enrol", json=_body(created["code"]))).status_code == 409


async def test_the_session_list_says_whether_the_device_is_online(client, auth_headers):
    created = await _live_session(client, auth_headers)
    await client.post("/connector/enrol", json=_body(created["code"]))
    listed = (await client.get("/sessions", headers=auth_headers)).json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["mode"] == "unattended"
    assert row["device_online"] is False  # no heartbeat has arrived


async def test_enrolment_is_rate_limited(client, auth_headers):
    seen_429 = False
    for _ in range(30):
        if (await client.post("/connector/enrol", json=_body("NOPE1234"))).status_code == 429:
            seen_429 = True
            break
    assert seen_429
