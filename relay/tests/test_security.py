"""Security review findings, kept honest by tests (Phase 6).

Each test here corresponds to a finding in docs/SECURITY_REVIEW.md.
"""
import pytest

from tests.conftest import TEST_EMAIL


async def test_password_guessing_is_throttled(client):
    """Nothing throttled login before the review; a script could grind at it."""
    seen_429 = False
    for _ in range(30):
        response = await client.post(
            "/auth/login", json={"email": TEST_EMAIL, "password": "wrong"}
        )
        if response.status_code == 429:
            seen_429 = True
            assert "Retry-After" in response.headers
            break
        assert response.status_code == 401
    assert seen_429, "login accepted 30 wrong passwords without throttling"


async def test_a_throttled_caller_is_told_when_to_retry(client):
    for _ in range(40):
        response = await client.post(
            "/auth/login", json={"email": TEST_EMAIL, "password": "wrong"}
        )
        if response.status_code == 429:
            assert int(response.headers["Retry-After"]) > 0
            assert "Too many attempts" in response.json()["detail"]
            return
    pytest.fail("never throttled")


async def test_session_code_probing_is_throttled(client):
    """/connector/session/{code} answers "is this code real?", so it is the
    cheapest way to hunt for live sessions."""
    seen_429 = False
    for i in range(40):
        response = await client.get(f"/connector/session/AAAA{i:04d}")
        if response.status_code == 429:
            seen_429 = True
            break
        assert response.status_code == 404
    assert seen_429, "session codes could be probed without limit"


async def test_the_connector_never_reveals_another_session(client, auth_headers):
    """A guest sees only their own session, and nothing about the operator."""
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()

    body = (await client.get(f"/connector/session/{created['code']}")).json()
    assert set(body) == {"code", "name", "waiting", "connected"}
    assert "operator_id" not in body
    assert "device_id" not in body
    assert "id" not in body


async def test_an_ended_session_code_stops_working(client, auth_headers):
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    assert (await client.get(f"/connector/session/{created['code']}")).status_code == 200

    await client.delete(f"/sessions/{created['id']}", headers=auth_headers)
    assert (await client.get(f"/connector/session/{created['code']}")).status_code == 404


async def test_session_codes_have_enough_entropy():
    """8 characters from a 31-character alphabet is about 2^40, which is only
    meaningful while guessing is rate limited."""
    import math

    from app.core.codes import ALPHABET
    from app.core.config import settings

    bits = settings.session_code_length * math.log2(len(ALPHABET))
    assert bits >= 38, f"session codes carry only {bits:.0f} bits"
    # No ambiguous characters: the code gets read aloud over the phone.
    assert not (set("01OIL") & set(ALPHABET))


async def test_device_secrets_are_never_returned_after_enrolment(client, auth_headers):
    device = (
        await client.post(
            "/devices", json={"name": "Bench", "os": "linux"}, headers=auth_headers
        )
    ).json()
    assert device["enrollment_secret"]

    listed = (await client.get("/devices", headers=auth_headers)).json()
    for entry in listed:
        assert "enrollment_secret" not in entry
        assert "secret_hash" not in entry


async def test_the_audit_trail_cannot_be_altered_through_the_api(client, auth_headers):
    for method in ("post", "put", "patch", "delete"):
        response = await getattr(client, method)("/audit", headers=auth_headers)
        assert response.status_code in (404, 405), f"{method} /audit was accepted"
