"""The session client: attach, ask for consent, then stream and take input."""
import asyncio
import json
import logging

import websockets

from rmm_agent import __version__, sysinfo
from rmm_agent.capture import RateController, ScreenCapture
from rmm_agent.consent import ask as ask_consent
from rmm_agent.remote_input import InputInjector
from rmm_agent.tray import CONNECTED, IDLE, SHARING, Tray

log = logging.getLogger(__name__)

# Spec section 8: the agent reconnects automatically after drops.
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0


class AgentSession:
    def __init__(
        self,
        relay_url: str,
        code: str,
        tray: Tray | None = None,
        *,
        fps: int = 12,
        quality: int = 60,
        budget_kbps: int = 0,
        synthetic: bool = False,
        inject: bool = True,
        auto_consent: bool = False,
        device_id: str = "",
        device_secret: str = "",
    ) -> None:
        self.relay_url = relay_url.rstrip("/")
        self.code = code.upper()
        self.tray = tray
        self.capture = ScreenCapture(synthetic=synthetic)
        self.injector = InputInjector(enabled=inject)
        self.rate = RateController(fps, quality)
        self.budget_kbps = budget_kbps
        self.auto_consent = auto_consent
        self.device_id = device_id
        self.device_secret = device_secret
        self._stop = asyncio.Event()
        self._frame_size = (0, 0)
        self._consented = False

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def endpoint(self) -> str:
        url = f"{self.relay_url}/ws/guest/{self.code}"
        if self.device_id and self.device_secret:
            from urllib.parse import quote

            url += f"?device_id={quote(self.device_id)}&secret={quote(self.device_secret)}"
        return url

    async def run_forever(self) -> None:
        backoff = BACKOFF_START
        while not self._stop.is_set():
            try:
                await self._run_once()
                backoff = BACKOFF_START
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("session connection failed: %s", exc)

            if self._stop.is_set():
                break
            if self._consented:
                # Consent is per session; a reconnect asks again.
                self._consented = False
            log.info("reconnecting in %.0fs", backoff)
            if self.tray:
                self.tray.set_state(IDLE, "Reconnecting…")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(BACKOFF_MAX, backoff * 2)

    async def _run_once(self) -> None:
        log.info("connecting to %s", self.endpoint.split("?")[0])
        async with websockets.connect(self.endpoint, max_size=None, ping_interval=20) as socket:
            info = sysinfo.collect()
            await socket.send(
                json.dumps(
                    {
                        "host_name": info["hostname"],
                        "system_info": info,
                        "monitors": self.capture.monitors,
                        "agent_version": __version__,
                    }
                )
            )
            log.info("attached to session %s as %s", self.code, info["hostname"])
            if self.tray:
                self.tray.set_state(CONNECTED, "Waiting for your decision")
                self.tray.notify(
                    f"A support operator is requesting session {self.code}.",
                    "Session requested",
                )

            granted = await asyncio.to_thread(
                ask_consent, self.code, None, 120.0, self.auto_consent
            )
            await socket.send(json.dumps({"type": "consent", "granted": granted}))

            if not granted:
                log.info("consent denied; nothing will be captured")
                if self.tray:
                    self.tray.set_state(IDLE, "Session denied")
                    self.tray.notify("You denied the session. Nothing was shared.", "Session denied")
                self._stop.set()
                return

            self._consented = True
            log.info("consent granted; streaming starts now")
            if self.tray:
                self.tray.set_state(SHARING, f"Sharing your screen — session {self.code}")
                self.tray.notify(
                    "Your screen is being shared. End the session from this menu at any time.",
                    "Session started",
                )

            receiver = asyncio.create_task(self._receive(socket))
            try:
                await self._stream(socket)
            finally:
                receiver.cancel()
                if self.tray:
                    self.tray.set_state(IDLE, "Not in a session")
                    self.tray.notify("The remote session has ended.", "Session ended")

    async def _stream(self, socket) -> None:
        while not self._stop.is_set():
            started = asyncio.get_running_loop().time()
            image = await asyncio.to_thread(self.capture.grab)
            self._frame_size = image.size
            payload = await asyncio.to_thread(self.capture.encode, image, self.rate.quality)
            await socket.send(payload)
            self.rate.record(len(payload))
            if self.budget_kbps:
                self.rate.adjust(self.budget_kbps)

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, self.rate.interval - elapsed))

    async def _receive(self, socket) -> None:
        async for raw in socket:
            if isinstance(raw, bytes):
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue

            kind = message.get("type")
            if kind == "input":
                self.injector.apply(message, self._frame_size)
            elif kind == "monitor":
                self.capture.select(int(message.get("index", 0)))
            elif kind == "blank":
                # The privacy blank itself is Phase 5. The message is recorded
                # here so the wiring is verifiable end to end.
                log.info("privacy blank %s (not implemented until Phase 5)",
                         "on" if message.get("on") else "off")
            elif kind == "end":
                log.info("the operator ended the session")
                self._stop.set()
                return
