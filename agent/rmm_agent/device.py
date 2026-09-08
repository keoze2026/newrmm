"""Unattended presence: hold a socket open so the console sees the device."""
import asyncio
import json
import logging
from urllib.parse import quote

import websockets

from rmm_agent import __version__

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 20


async def hold_presence(relay_url: str, device_id: str, secret: str, stop: asyncio.Event) -> None:
    url = f"{relay_url.rstrip('/')}/ws/device/{quote(device_id)}?secret={quote(secret)}"
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=20) as socket:
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
