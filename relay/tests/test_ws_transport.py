"""The session transport (/ws/*), driven over real sockets.

The relay runs in a subprocess (uvicorn) against the same test database, and
the tests connect to it the way the agent and the console do. Before this file
the WebSocket routes had no relay tests at all.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import websockets
from sqlalchemy import select

from app.core.security import hash_secret
from app.db.session import SessionLocal
from app.models import Device
from app.models import Session as SessionRow

from .conftest import RELAY_ROOT


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
async def relay_url(migrated_database):
    port = _free_port()
    env = os.environ.copy()
    env["LOG_DIR"] = ""
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=RELAY_ROOT, env=env,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            await asyncio.sleep(0.2)
    else:
        process.kill()
        raise RuntimeError("relay did not start")
    yield f"ws://127.0.0.1:{port}"
    process.terminate()
    process.wait(timeout=10)


async def _new_session(client, auth_headers) -> dict:
    return (await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)).json()


async def _token(client) -> str:
    from .conftest import TEST_EMAIL, TEST_PASSWORD

    response = await client.post("/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    return response.json()["access_token"]


def _hello(**extra) -> str:
    return json.dumps({"host_name": "pc", "system_info": {"os": "linux"}, "monitors": [], **extra})


async def _recv_json(ws, timeout=5.0) -> dict:
    while True:
        message = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(message, str):
            return json.loads(message)


async def _closed_code(ws, timeout=5.0) -> int | None:
    try:
        while True:
            await asyncio.wait_for(ws.recv(), timeout=timeout)
    except websockets.ConnectionClosed as exc:
        return exc.rcvd.code if exc.rcvd else None


async def test_the_first_computer_in_is_given_a_secret(relay_url, client, auth_headers):
    session = await _new_session(client, auth_headers)
    async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as ws:
        await ws.send(_hello(token_aware=True))
        welcome = await _recv_json(ws)
        assert welcome["type"] == "welcome"
        assert welcome["guest_token"] and len(welcome["guest_token"]) >= 32

    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == uuid.UUID(session["id"])))
        # Only the hash is kept.
        assert row.guest_token_hash and welcome["guest_token"] not in row.guest_token_hash


async def test_the_code_alone_cannot_replace_the_computer_in_the_session(
    relay_url, client, auth_headers
):
    """Security finding: anyone holding the code could replace the connected
    guest and report consent in its name."""
    session = await _new_session(client, auth_headers)
    url = f"{relay_url}/ws/guest/{session['code']}"
    async with websockets.connect(url) as real:
        await real.send(_hello(token_aware=True))
        await _recv_json(real)

        for hello in (_hello(token_aware=True), _hello(), _hello(guest_token="guess")):
            async with websockets.connect(url) as intruder:
                await intruder.send(hello)
                assert await _closed_code(intruder) == 4401

        # The real computer was not displaced: its consent still lands.
        await real.send(json.dumps({"type": "consent", "granted": True}))
        await asyncio.sleep(0.5)
        fetched = (await client.get(f"/sessions/{session['id']}", headers=auth_headers)).json()
        assert fetched["consent_state"] == "granted"

    logs = (await client.get(f"/sessions/{session['id']}/logs", headers=auth_headers)).json()
    assert sum(1 for e in logs if e["action"] == "session.guest_refused") == 3


async def test_the_bound_computer_reconnects_with_its_secret(relay_url, client, auth_headers):
    session = await _new_session(client, auth_headers)
    url = f"{relay_url}/ws/guest/{session['code']}"
    old = await websockets.connect(url)
    await old.send(_hello(token_aware=True))
    token = (await _recv_json(old))["guest_token"]

    async with websockets.connect(url) as again:
        await again.send(_hello(token_aware=True, guest_token=token))
        welcome = await _recv_json(again)
        assert welcome["type"] == "welcome"
        # Already bound: no new secret is handed out.
        assert welcome["guest_token"] is None
        assert await _closed_code(old) == 4409


async def test_an_agent_too_old_to_keep_a_secret_still_joins(relay_url, client, auth_headers):
    """Agents already installed never ask for a secret and must keep working."""
    session = await _new_session(client, auth_headers)
    url = f"{relay_url}/ws/guest/{session['code']}"
    async with websockets.connect(url) as first:
        await first.send(_hello())
        assert (await _recv_json(first))["guest_token"] is None
    async with websockets.connect(url) as second:
        await second.send(_hello())
        assert (await _recv_json(second))["type"] == "welcome"


async def test_a_socket_that_never_says_hello_is_dropped(relay_url, client, auth_headers, monkeypatch):
    session = await _new_session(client, auth_headers)
    async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as ws:
        await ws.send("not json")
        assert await _closed_code(ws) == 4400


async def test_enrolling_needs_the_secret_of_the_computer_in_the_session(
    relay_url, client, auth_headers
):
    """Security finding: /connector/enrol accepted the code alone, so anyone who
    had seen it could enrol their own machine into a consented session."""
    session = await _new_session(client, auth_headers)
    async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as ws:
        await ws.send(_hello(token_aware=True))
        token = (await _recv_json(ws))["guest_token"]
        await ws.send(json.dumps({"type": "consent", "granted": True}))
        await asyncio.sleep(0.5)

        body = {"code": session["code"], "name": "pc", "os": "linux"}
        assert (await client.post("/connector/enrol", json=body)).status_code == 403
        wrong = {**body, "guest_token": "x" * 43}
        assert (await client.post("/connector/enrol", json=wrong)).status_code == 403
        right = await client.post("/connector/enrol", json={**body, "guest_token": token})
        assert right.status_code == 201, right.text


async def _device(secret: str) -> str:
    async with SessionLocal() as db:
        device = Device(name="box", os="linux", secret_hash=hash_secret(secret), status="offline")
        db.add(device)
        await db.commit()
        return str(device.id)


async def _device_status(device_id: str) -> str:
    async with SessionLocal() as db:
        device = await db.scalar(select(Device).where(Device.id == uuid.UUID(device_id)))
        return device.status


async def test_a_device_authenticates_in_its_first_message(relay_url):
    """The secret no longer has to travel in the URL (proxy access logs)."""
    device_id = await _device("s3cret-value")
    async with websockets.connect(f"{relay_url}/ws/device/{device_id}") as ws:
        await ws.send(json.dumps({"type": "auth", "secret": "s3cret-value"}))
        await asyncio.sleep(0.5)
        assert await _device_status(device_id) == "online"
    await asyncio.sleep(0.5)
    assert await _device_status(device_id) == "offline"


async def test_a_device_with_the_wrong_secret_is_refused(relay_url):
    device_id = await _device("right")
    async with websockets.connect(f"{relay_url}/ws/device/{device_id}") as ws:
        await ws.send(json.dumps({"type": "auth", "secret": "wrong"}))
        assert await _closed_code(ws) == 4401
    assert await _device_status(device_id) == "offline"


async def test_an_older_agent_with_the_secret_in_the_url_still_connects(relay_url):
    device_id = await _device("legacy")
    async with websockets.connect(f"{relay_url}/ws/device/{device_id}?secret=legacy") as ws:
        await asyncio.sleep(0.5)
        assert await _device_status(device_id) == "online"
        await ws.close()


async def test_the_operator_authenticates_in_its_first_message(relay_url, client, auth_headers):
    session = await _new_session(client, auth_headers)
    token = await _token(client)
    async with websockets.connect(f"{relay_url}/ws/operator/{session['code']}") as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        attached = await _recv_json(ws)
        assert attached["type"] == "attached"


async def test_the_endpoints_privacy_mode_reaches_the_operator(relay_url, client, auth_headers):
    """The console warns before blanking and shows the right banner only if it
    knows what the endpoint can do. The relay used to drop privacy_mode, so the
    console assumed the operator kept their view even on a guest-lock endpoint."""
    session = await _new_session(client, auth_headers)
    token = await _token(client)
    async with websockets.connect(f"{relay_url}/ws/operator/{session['code']}") as op:
        await op.send(json.dumps({"type": "auth", "token": token}))
        await _recv_json(op)  # "attached" - no guest yet
        async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as guest:
            await guest.send(_hello(token_aware=True, privacy_mode="guest-lock"))
            await _recv_json(guest)
            assert (await _recv_json(op))["type"] == "guest_attached"
            await guest.send(json.dumps({"type": "consent", "granted": True}))
            joined = await _recv_json(op)
            assert joined["type"] == "guest_joined"
            assert joined["privacy_mode"] == "guest-lock"

    # A second operator opening the already-live session learns it too, from the
    # persisted row (the "attached" message), without waiting for a new consent.
    async with websockets.connect(f"{relay_url}/ws/operator/{session['code']}") as op2:
        await op2.send(json.dumps({"type": "auth", "token": token}))
        attached = await _recv_json(op2)
        assert attached["type"] == "attached"
        assert attached["privacy_mode"] == "guest-lock"


async def test_an_operator_without_a_valid_token_is_refused(relay_url, client, auth_headers):
    session = await _new_session(client, auth_headers)
    async with websockets.connect(f"{relay_url}/ws/operator/{session['code']}") as ws:
        await ws.send(json.dumps({"type": "auth", "token": "nope"}))
        assert await _closed_code(ws) == 4401


async def test_nothing_reaches_the_operator_before_consent(relay_url, client, auth_headers):
    session = await _new_session(client, auth_headers)
    token = await _token(client)
    async with websockets.connect(f"{relay_url}/ws/operator/{session['code']}") as op:
        await op.send(json.dumps({"type": "auth", "token": token}))
        assert (await _recv_json(op))["type"] == "attached"
        async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as guest:
            await guest.send(_hello(token_aware=True))
            await _recv_json(guest)
            assert (await _recv_json(op))["type"] == "guest_attached"
            await guest.send(b"frame-before-consent")
            await guest.send(json.dumps({"type": "consent", "granted": True}))
            assert (await _recv_json(op))["type"] == "guest_joined"
            await guest.send(b"frame-after-consent")
            got = await asyncio.wait_for(op.recv(), timeout=5)
            assert got == b"frame-after-consent"


async def test_when_the_guest_leaves_the_session_stops_reading_connected(
    relay_url, client, auth_headers
):
    session = await _new_session(client, auth_headers)
    async with websockets.connect(f"{relay_url}/ws/guest/{session['code']}") as guest:
        await guest.send(_hello(token_aware=True))
        await _recv_json(guest)
        await guest.send(json.dumps({"type": "consent", "granted": True}))
        await asyncio.sleep(0.5)
    await asyncio.sleep(0.5)
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == uuid.UUID(session["id"])))
        assert row.guest_connected is False


async def test_a_used_code_dies_a_day_after_its_guest_was_last_seen(client, auth_headers):
    """Security finding: a session consented once stayed joinable for ever."""
    from app.services.sessions import is_expired

    now = datetime.now(timezone.utc)
    row = SessionRow(
        code="USED1234", name="used", mode="attended", state="active",
        expires_at=now - timedelta(days=3), guest_connected=False, consent_state="granted",
        guest_last_seen_at=now - timedelta(hours=25),
    )
    assert is_expired(row, now) is True
    row.guest_last_seen_at = now - timedelta(hours=2)
    assert is_expired(row, now) is False


class _DeadSocket:
    async def send_json(self, payload):
        raise RuntimeError("peer gone")

    async def send_bytes(self, payload):
        raise RuntimeError("peer gone")


async def test_a_failed_send_leaves_cleanup_to_the_sockets_own_handler():
    """Security/cleanup finding: a failed send cleared the socket, so the
    handler's own `finally` thought a newer connection had taken over and
    skipped marking the session disconnected."""
    from app.services.hub import Hub

    hub = Hub()
    hub._redis_failed = True
    dead = _DeadSocket()
    channel = hub.channel("DEAD0001")
    channel.guest = dead
    channel.operator = dead
    await hub.to_guest_json("DEAD0001", {"type": "x"})
    await hub.to_operator_json("DEAD0001", {"type": "x"})
    await hub.to_operator_bytes("DEAD0001", b"x")
    assert channel.guest is dead and channel.operator is dead
    hub._devices["dev"] = dead
    await hub.to_device_json("dev", {"type": "x"})
    assert hub.device_online("dev")


class _GoodSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_bytes(self, payload):
        self.sent.append(("b", payload))

    async def send_json(self, payload):
        self.sent.append(("j", payload))

    async def send_text(self, payload):
        self.sent.append(("t", payload))

    async def close(self, code=1000):
        self.closed = True


async def test_a_healthy_operator_send_delivers_and_is_not_closed():
    from app.services.hub import Hub

    hub = Hub()
    hub._redis_failed = True
    channel = hub.channel("GOOD0001")
    good = _GoodSocket()
    channel.operator = good

    await hub.to_operator_bytes("GOOD0001", b"frame")
    await hub.to_operator_json("GOOD0001", {"type": "ping"})

    assert good.sent == [("b", b"frame"), ("j", {"type": "ping"})]
    assert good.closed is False


async def test_concurrent_frame_and_heartbeat_sends_are_serialized():
    """The 1s heartbeat and the frame forwarder both write the operator socket;
    the channel lock must keep them from interleaving, and all must arrive."""
    from app.services.hub import Hub

    hub = Hub()
    hub._redis_failed = True
    channel = hub.channel("RACE0001")
    good = _GoodSocket()
    channel.operator = good

    await asyncio.gather(
        *[hub.to_operator_bytes("RACE0001", b"f") for _ in range(5)],
        *[hub.to_operator_json("RACE0001", {"type": "ping"}) for _ in range(5)],
    )
    assert len(good.sent) == 10


async def test_the_rate_limit_still_holds_when_redis_fails_mid_run(monkeypatch):
    """Security finding: a Redis error let every attempt through."""
    from app.services import ratelimit

    class Broken:
        async def incr(self, *a):
            raise ConnectionError("redis down")

        async def sadd(self, *a):
            raise ConnectionError("redis down")

    async def broken_client():
        return Broken()

    monkeypatch.setattr(ratelimit, "_client", broken_client)
    results = [(await ratelimit.hit("t:fail", limit=3, window=60))[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    distinct = [(await ratelimit.hit_distinct("t:d", f"m{i}", limit=2, window=60))[0] for i in range(4)]
    assert distinct == [True, True, False, False]
