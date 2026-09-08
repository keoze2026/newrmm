"""In-process relay between the operator console and the endpoint guest.

One session has at most one guest socket and one operator socket. Screen frames
travel guest -> operator as binary; control messages travel both ways as JSON.

This is deliberately single-process. Phase 6 moves the fan-out onto the Redis
pub/sub layer so several relay instances can share sessions; until then a
deployment runs one relay process.
"""
import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class SessionChannel:
    guest: WebSocket | None = None
    operator: WebSocket | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Hub:
    def __init__(self) -> None:
        self._channels: dict[str, SessionChannel] = {}

    def channel(self, code: str) -> SessionChannel:
        return self._channels.setdefault(code, SessionChannel())

    def drop(self, code: str) -> None:
        channel = self._channels.get(code)
        if channel and channel.guest is None and channel.operator is None:
            self._channels.pop(code, None)

    def guest_online(self, code: str) -> bool:
        channel = self._channels.get(code)
        return bool(channel and channel.guest is not None)

    async def to_operator_bytes(self, code: str, payload: bytes) -> None:
        channel = self._channels.get(code)
        if channel and channel.operator is not None:
            try:
                await channel.operator.send_bytes(payload)
            except Exception:
                channel.operator = None

    async def to_operator_json(self, code: str, payload: dict) -> None:
        channel = self._channels.get(code)
        if channel and channel.operator is not None:
            try:
                await channel.operator.send_json(payload)
            except Exception:
                channel.operator = None

    async def close_session(self, code: str, reason: str = "Session ended") -> None:
        """Hang up on both halves of a session.

        Ending a session must actually stop the endpoint capturing. Marking the
        row 'ended' while the agent keeps streaming would leave capture running
        outside a consented session.
        """
        channel = self._channels.get(code)
        if channel is None:
            return
        for socket in (channel.guest, channel.operator):
            if socket is None:
                continue
            try:
                await socket.close(code=4404, reason=reason)
            except Exception:
                pass
        channel.guest = None
        channel.operator = None
        self._channels.pop(code, None)

    async def to_guest_json(self, code: str, payload: dict) -> None:
        channel = self._channels.get(code)
        if channel and channel.guest is not None:
            try:
                await channel.guest.send_json(payload)
            except Exception:
                channel.guest = None


hub = Hub()
