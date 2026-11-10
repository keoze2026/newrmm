"""Relay between the operator console and the endpoint guest.

One session has at most one guest socket and one operator socket. Screen frames
travel guest -> operator as binary; control messages travel both ways as JSON.

The two halves of a session need not be on the same relay process. The
specification calls the relay "horizontally scalable" (section 3) and names
Redis pub/sub in the stack, so when the peer is not attached to this instance
the message is published to Redis and delivered by whichever instance holds it.
A single-instance deployment never touches Redis: the local path is checked
first, so the common case costs nothing.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket
from redis.asyncio import Redis

from app.core.config import settings

log = logging.getLogger(__name__)

# A send to an operator socket must complete within this long. A half-open
# socket (NAT/wifi-roam/sleep, or a proxy dropping one direction) makes
# send_bytes/send_json await the kernel buffer draining *forever* - not an
# error, a hang - which stalls the guest read loop that awaits it and so blocks
# the agent's own send, freezing the stream at 0 fps. On timeout the socket is
# closed so its handler cleans up and the console reconnects onto a fresh one.
OPERATOR_SEND_TIMEOUT = 2.0

# Channel names. Binary frames and JSON travel separately so the subscriber
# never has to guess which it is holding.
def operator_binary_channel(code: str) -> str:
    return f"rmm:{code}:operator:bin"


def operator_json_channel(code: str) -> str:
    return f"rmm:{code}:operator:json"


def guest_json_channel(code: str) -> str:
    return f"rmm:{code}:guest:json"


def device_json_channel(device_id: str) -> str:
    return f"rmm:device:{device_id}:json"


@dataclass
class SessionChannel:
    guest: WebSocket | None = None
    operator: WebSocket | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Tasks listening on this session's Redis channels, one per attached role.
    subscriptions: list[asyncio.Task] = field(default_factory=list)


class Hub:
    def __init__(self) -> None:
        self._channels: dict[str, SessionChannel] = {}
        # Enrolled devices holding a presence socket on this instance.
        self._devices: dict[str, WebSocket] = {}
        self._device_tasks: dict[str, asyncio.Task] = {}
        self._redis: Redis | None = None
        self._redis_failed = False

    # ------------------------------------------------------------- plumbing

    async def _client(self) -> Redis | None:
        """The shared Redis client, or None when Redis is unreachable.

        A relay that cannot reach Redis still serves every session whose two
        halves are on this instance, which is the whole of a single-instance
        deployment. It logs once rather than on every message.
        """
        if self._redis_failed:
            return None
        if self._redis is None:
            try:
                self._redis = Redis.from_url(settings.redis_url)
                await self._redis.ping()
            except Exception as exc:
                log.warning(
                    "Redis is unavailable (%s); sessions are limited to this "
                    "relay instance", exc,
                )
                self._redis_failed = True
                self._redis = None
        return self._redis

    async def _publish(self, channel: str, payload: bytes) -> bool:
        client = await self._client()
        if client is None:
            return False
        try:
            await client.publish(channel, payload)
            return True
        except Exception as exc:
            log.debug("could not publish to %s: %s", channel, exc)
            return False

    async def _subscribe(self, channel: str, deliver) -> asyncio.Task | None:
        """Listen on a channel and hand each message to `deliver`."""
        client = await self._client()
        if client is None:
            return None

        async def listen() -> None:
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(channel)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        await deliver(message["data"])
                    except Exception:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("subscription to %s ended: %s", channel, exc)
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass

        return asyncio.create_task(listen())

    # ------------------------------------------------------------- channels

    def channel(self, code: str) -> SessionChannel:
        return self._channels.setdefault(code, SessionChannel())

    def drop(self, code: str) -> None:
        channel = self._channels.get(code)
        if channel and channel.guest is None and channel.operator is None:
            for task in channel.subscriptions:
                task.cancel()
            self._channels.pop(code, None)

    def guest_online(self, code: str) -> bool:
        """Whether a guest socket is attached *to this instance*.

        Cross-instance presence is answered by the session row, which every
        instance writes to the same database.
        """
        channel = self._channels.get(code)
        return bool(channel and channel.guest is not None)

    def device_online(self, device_id: str) -> bool:
        """Whether an enrolled device is holding a socket *on this instance*."""
        return device_id in self._devices

    async def attach_device(self, device_id: str, websocket: WebSocket) -> None:
        """Register a device here and listen for messages aimed at it."""
        self._devices[device_id] = websocket

        async def deliver(data: bytes) -> None:
            socket = self._devices.get(device_id)
            if socket is not None:
                await socket.send_text(data.decode("utf-8"))

        old = self._device_tasks.pop(device_id, None)
        if old is not None:
            old.cancel()
        task = await self._subscribe(device_json_channel(device_id), deliver)
        if task is not None:
            self._device_tasks[device_id] = task

    def detach_device(self, device_id: str, websocket: WebSocket) -> None:
        """Forget a device's socket, unless a newer one has already replaced it."""
        if self._devices.get(device_id) is websocket:
            self._devices.pop(device_id, None)
            task = self._device_tasks.pop(device_id, None)
            if task is not None:
                task.cancel()

    def detach_guest(self, code: str, websocket: WebSocket) -> None:
        """Forget a guest's socket, unless a newer one has already replaced it.

        A reconnect can attach a new socket before the old one's read loop has
        noticed it is dead (TCP teardown is not instant). Without this check,
        the old socket's own cleanup would clobber the new, live one - exactly
        the bug `detach_device` above was already written to avoid.
        """
        channel = self._channels.get(code)
        if channel is not None and channel.guest is websocket:
            channel.guest = None

    def detach_operator(self, code: str, websocket: WebSocket) -> None:
        """Forget an operator's socket, unless a newer one has already replaced it."""
        channel = self._channels.get(code)
        if channel is not None and channel.operator is websocket:
            channel.operator = None

    async def attach_guest(self, code: str, websocket: WebSocket) -> None:
        """Register a guest here and listen for messages aimed at it."""
        channel = self.channel(code)
        channel.guest = websocket

        async def deliver(data: bytes) -> None:
            socket = self._channels.get(code, SessionChannel()).guest
            if socket is not None:
                await socket.send_text(data.decode("utf-8"))

        task = await self._subscribe(guest_json_channel(code), deliver)
        if task is not None:
            channel.subscriptions.append(task)

    async def attach_operator(self, code: str, websocket: WebSocket) -> None:
        """Register an operator here and listen for frames aimed at it."""
        channel = self.channel(code)
        channel.operator = websocket

        async def deliver_binary(data: bytes) -> None:
            ch = self._channels.get(code)
            if ch and ch.operator is not None:
                await self._send_operator(ch, lambda s: s.send_bytes(data))

        async def deliver_json(data: bytes) -> None:
            ch = self._channels.get(code)
            if ch and ch.operator is not None:
                await self._send_operator(ch, lambda s: s.send_text(data.decode("utf-8")))

        for name, deliver in (
            (operator_binary_channel(code), deliver_binary),
            (operator_json_channel(code), deliver_json),
        ):
            task = await self._subscribe(name, deliver)
            if task is not None:
                channel.subscriptions.append(task)

    # ------------------------------------------------------------- delivery

    async def _send_operator(self, channel: SessionChannel, send) -> None:
        """The one guarded way to write an operator socket.

        Serialized by the channel lock, because two coroutines now write it -
        the frame/JSON forwarder and the 1 s heartbeat - and one WebSocket must
        never be written by two at once. Bounded by OPERATOR_SEND_TIMEOUT: a
        send that cannot finish in that time means the socket is half-open, so
        it is closed (the console then reconnects) rather than left to hang the
        guest loop. Any other send error is swallowed and the socket left in
        place, exactly as before, so its own handler's `finally` still runs (a
        failed send must not look like a newer connection taking over).
        """
        socket = channel.operator
        if socket is None:
            return
        try:
            async with channel.lock:
                # A reconnect may have swapped the socket while we waited for
                # the lock; the new one gets the next message, not this.
                if channel.operator is not socket:
                    return
                await asyncio.wait_for(send(socket), OPERATOR_SEND_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning(
                "an operator send stalled for >%ss (half-open socket); closing "
                "it so the console reconnects", OPERATOR_SEND_TIMEOUT,
            )
            try:
                await socket.close(code=1011)
            except Exception:
                pass
        except Exception as exc:
            log.debug("send to operator failed: %s", exc)

    async def to_operator_bytes(self, code: str, payload: bytes) -> None:
        channel = self._channels.get(code)
        if channel and channel.operator is not None:
            await self._send_operator(channel, lambda s: s.send_bytes(payload))
            return
        await self._publish(operator_binary_channel(code), payload)

    async def to_operator_json(self, code: str, payload: dict) -> None:
        channel = self._channels.get(code)
        if channel and channel.operator is not None:
            await self._send_operator(channel, lambda s: s.send_json(payload))
            return
        await self._publish(operator_json_channel(code), json.dumps(payload).encode())

    async def to_guest_json(self, code: str, payload: dict) -> None:
        channel = self._channels.get(code)
        if channel and channel.guest is not None:
            try:
                await channel.guest.send_json(payload)
            except Exception as exc:
                # Leave the socket where it is. Its own handler notices it is
                # dead and cleans up; clearing it here made that handler think
                # a newer connection had taken over, so it skipped the cleanup
                # (session left "connected", a standing device kept streaming).
                log.debug("send to %s of %s failed: %s", "guest", code, exc)
            return
        await self._publish(guest_json_channel(code), json.dumps(payload).encode())

    async def to_device_json(self, device_id: str, payload: dict) -> None:
        """Send to an enrolled device: directly if it is here, else through Redis."""
        socket = self._devices.get(device_id)
        if socket is not None:
            try:
                await socket.send_json(payload)
            except Exception as exc:
                # Same as above: the device handler's own cleanup owns this.
                log.debug("send to device %s failed: %s", device_id, exc)
            return
        await self._publish(device_json_channel(device_id), json.dumps(payload).encode())

    async def close_session(self, code: str, reason: str = "Session ended") -> None:
        """Hang up on both halves of a session.

        Ending a session must actually stop the endpoint capturing. Marking the
        row 'ended' while the agent keeps streaming would leave capture running
        outside a consented session.
        """
        channel = self._channels.get(code)
        if channel is not None:
            for socket in (channel.guest, channel.operator):
                if socket is None:
                    continue
                try:
                    await socket.close(code=4404, reason=reason)
                except Exception:
                    pass
            for task in channel.subscriptions:
                task.cancel()
            channel.guest = None
            channel.operator = None
            self._channels.pop(code, None)

        # Another instance may hold the other half; tell it to hang up too.
        await self._publish(
            guest_json_channel(code), json.dumps({"type": "session_ended"}).encode()
        )
        await self._publish(
            operator_json_channel(code), json.dumps({"type": "session_ended"}).encode()
        )


hub = Hub()
