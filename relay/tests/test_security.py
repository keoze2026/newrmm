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


async def test_asking_about_the_same_code_repeatedly_is_not_probing(client):
    """The join page asks about its own code every 4 seconds, and the agent
    checks it too. That is one code, not a hunt, and must never be throttled
    at the rate that guessing is."""
    for _ in range(60):
        response = await client.get("/connector/session/SAMECODE")
        assert response.status_code == 404, "a guest's own repeat checks were throttled"


async def test_hunting_many_different_codes_is_still_throttled_after_repeats(client):
    for _ in range(30):
        await client.get("/connector/session/SAMECODE")
    seen_429 = False
    for i in range(40):
        response = await client.get(f"/connector/session/HUNT{i:04d}")
        if response.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "different codes could be tried without limit"


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakePeer:
    """Shaped like both a Request and a WebSocket: same .headers/.client the
    real ones expose, which is all `caller()` is allowed to depend on."""

    def __init__(self, peer_host, forwarded_for=None):
        self.client = _FakeClient(peer_host)
        self.headers = _FakeHeaders()
        if forwarded_for:
            self.headers["x-forwarded-for"] = forwarded_for


async def test_rate_limiting_uses_the_real_visitor_not_the_reverse_proxy():
    """Behind nginx, every connection's raw TCP peer is nginx itself - the same
    address for every visitor. A guest join's rate limit found and fixed this
    exact bug (relay/app/api/ws.py): it read the raw peer instead of
    X-Forwarded-For, turning a 20-per-minute per-caller limit into one shared
    global bucket that any normal traffic could exhaust for everyone."""
    from app.services import ratelimit

    behind_proxy = _FakePeer("172.20.0.5", forwarded_for="203.0.113.7, 172.20.0.5")
    assert ratelimit.caller(behind_proxy) == "203.0.113.7"

    direct = _FakePeer("203.0.113.9")
    assert ratelimit.caller(direct) == "203.0.113.9"
