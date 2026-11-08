"""Unattended presence: hold a socket open so the console sees the device."""
import asyncio
import contextlib
import json
import logging
from urllib.parse import quote

import websockets

from rmm_agent import __version__

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 20


@contextlib.asynccontextmanager
async def connect_device(relay_url: str, device_id: str, secret: str, **options):
    """Open the presence socket and authenticate in the first message.

    The secret used to travel in the URL, which the reverse proxy writes to its
    access log. A relay older than first-message auth refuses the handshake
    with 403; only then is the URL form used.
    """
    base = f"{relay_url.rstrip('/')}/ws/device/{quote(device_id)}"
    connection = websockets.connect(base, **options)
    legacy = False
    try:
        socket = await connection.__aenter__()
    except websockets.InvalidStatus as exc:
        if exc.response.status_code != 403:
            raise
        connection = websockets.connect(f"{base}?secret={quote(secret)}", **options)
        socket = await connection.__aenter__()
        legacy = True
    try:
        if not legacy:
            await socket.send(json.dumps({"type": "auth", "secret": secret}))
        yield socket
    except BaseException as exc:
        if not await connection.__aexit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        await connection.__aexit__(None, None, None)


async def hold_presence(relay_url: str, device_id: str, secret: str, stop: asyncio.Event) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            async with connect_device(relay_url, device_id, secret, ping_interval=20) as socket:
                log.info("device %s is online", device_id)
                backoff = 1.0
                while not stop.is_set():
                    await socket.send(json.dumps({"type": "heartbeat", "agent": __version__}))
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("device presence lost: %s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(30.0, backoff * 2)


HEALTHY_SECONDS = 30.0


async def serve(
    relay_url: str,
    device_id: str,
    secret: str,
    on_start,
    stop: asyncio.Event,
    on_revoked=None,
) -> None:
    """Stay online for as long as the agent runs, and start sessions on request.

    This never gives up: after sleep, a network change, the relay restarting, or
    a handshake the relay turns away, it keeps retrying until it is back. A
    rejected handshake arrives as a plain 403 regardless of why the relay sent
    it, so it cannot be told apart from a real "this device was removed" - it is
    retried like any other drop rather than treated as final. The only way out
    is `stop`. `on_revoked` is kept for a future, unambiguous revoke signal; it
    is not called today.

    `on_start(code)` is called when an operator opens this device's session. It
    runs as its own task so a long session never blocks the connection, and a
    second request while one is running is ignored.
    """
    import time

    backoff = 1.0
    active: asyncio.Task | None = None

    async def beat(socket) -> None:
        while not stop.is_set():
            await socket.send(json.dumps({"type": "heartbeat", "agent": __version__}))
            try:
                await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                continue

    while not stop.is_set():
        started = time.monotonic()
        try:
            async with connect_device(
                relay_url, device_id, secret, ping_interval=20, ping_timeout=20
            ) as socket:
                log.info("device %s is online", device_id)
                heartbeat = asyncio.create_task(beat(socket))
                try:
                    async for raw in socket:
                        if isinstance(raw, bytes):
                            continue
                        try:
                            message = json.loads(raw)
                        except ValueError:
                            continue
                        if message.get("type") == "start_session" and message.get("code"):
                            if active is None or active.done():
                                log.info("an operator opened session %s", message["code"])
                                active = asyncio.create_task(on_start(str(message["code"])))
                finally:
                    heartbeat.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("device presence lost: %s", exc)

        if stop.is_set():
            break
        # A connection that held for a while was a working one; one that was
        # turned away or dropped at once means wait longer, up to 30 s.
        backoff = 1.0 if time.monotonic() - started >= HEALTHY_SECONDS else min(30.0, backoff * 2)
        log.info("reconnecting in %.0fs", backoff)
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass

    if active is not None and not active.done():
        active.cancel()

