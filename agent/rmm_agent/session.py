"""The session client: attach, ask for consent, then stream and take input."""
import asyncio
import json
import logging
import time

import websockets

from rmm_agent import __version__, clipboard, files, platform_support, privacy, sysinfo
from rmm_agent.capture import RateController, ScreenCapture
from rmm_agent.consent import ask_choice as ask_consent_choice
from rmm_agent.remote_input import InputInjector
from rmm_agent.terminal import RemoteTerminal, default_shell
from rmm_agent.tiles import TileEncoder
from rmm_agent.tray import CONNECTED, IDLE, SHARING, Tray

log = logging.getLogger(__name__)

# Spec section 8: the agent reconnects automatically after drops.
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
# A connection that lasted this long was a working one; a shorter one means the
# relay or this machine is turning it away, so the delay must keep growing.
HEALTHY_SECONDS = 30.0
# Retrying cannot fix these: the session ended (4404), consent was refused
# (4403), or the device credentials were rejected (4401).
GIVE_UP_CODES = (4401, 4403, 4404)
# A link that drops during a consented session and comes back within this long
# is the same session carrying on. Asking again would put a window in front of
# someone who is not there, and an unanswered window ends the agent for good.
RESUME_SECONDS = 300.0


def can_resume(streamed_until: float | None, now: float) -> bool:
    """Whether a reconnect continues a session the endpoint user already allowed."""
    return streamed_until is not None and 0 <= now - streamed_until <= RESUME_SECONDS


def next_backoff(current: float, lasted: float) -> float:
    """The delay before the next attempt: back to the start only after a
    connection that actually worked, otherwise longer."""
    if lasted >= HEALTHY_SECONDS:
        return BACKOFF_START
    return min(BACKOFF_MAX, current * 2)


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
        on_over=None,
        standing_allowed: bool = False,
        on_standing=None,
        standing_consent: bool = False,
        single_shot: bool = False,
        device_id: str = "",
        device_secret: str = "",
        blank_watchdog: float = 0.0,
        blank_blocks_input: bool = True,
    ) -> None:
        self.relay_url = relay_url.rstrip("/")
        self.code = code.upper()
        self.tray = tray
        platform_support.prepare()
        self.capture = ScreenCapture(synthetic=synthetic)
        self.injector = InputInjector(enabled=inject)
        self.rate = RateController(fps, quality)
        self.budget_kbps = budget_kbps
        self.auto_consent = auto_consent
        self.device_id = device_id
        self.device_secret = device_secret
        self._stop = asyncio.Event()
        self.on_over = on_over
        # "Always allow" is offered in the consent window, and when chosen
        # `on_standing` enrols this computer. `enrolled` tells the caller to stay
        # online as an always-on device once this session is over.
        self.standing_allowed = standing_allowed
        self.on_standing = on_standing
        self.enrolled = False
        # A session an enrolled device starts because an operator opened it: no
        # window, because the person gave permission once; it ends when the
        # connection does, and the operator opening it again starts a new one.
        self.standing_consent = standing_consent
        self.single_shot = single_shot
        self._consented = False
        self._streamed_until: float | None = None
        self._terminal: RemoteTerminal | None = None
        self._privacy = privacy.PrivacyBlank(watchdog_seconds=blank_watchdog)
        # Changed-region streaming (specification section 10).
        self._tiles = TileEncoder()
        self._blank_blocks_input = blank_blocks_input
        self._uploads: dict[str, files.Upload] = {}
        self._socket = None

    def _over(self) -> None:
        """The session ended for good, or consent was refused: nothing to rejoin."""
        if self.on_over is not None:
            try:
                self.on_over()
            except Exception as exc:
                log.warning("could not clean up after the session: %s", exc)

    async def _enrol(self) -> None:
        """The person chose "Always allow": make this computer an always-on device."""
        try:
            done = await asyncio.to_thread(self.on_standing)
        except Exception as exc:
            log.warning("could not turn on always-on access: %s", exc)
            done = False
        if done:
            self.enrolled = True
            # From now on starting again after a restart belongs to the device,
            # not to this one session, so this session ending is not the end.
            self.on_over = None
            if self.tray:
                self.tray.notify(
                    "This computer will stay connected so support can reach it. "
                    "Turn it off from this menu any time.",
                    "Always allow is on",
                )
        elif self.tray:
            self.tray.notify("Could not turn on always-on access. This session still works.", "Always allow")

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
            started = time.monotonic()
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except websockets.ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd is not None else None
                if code in GIVE_UP_CODES:
                    log.info("the session is over (%s); stopping", exc.rcvd.reason or code)
                    self._over()
                    self._stop.set()
                    break
                if code == 4409:
                    log.warning("another agent is already connected to this session")
                log.warning("session connection lost: %s", exc)
            except Exception as exc:
                log.warning("session connection failed: %s", exc)

            if self._stop.is_set():
                break
            if self.single_shot:
                break
            if self._consented:
                # Consent is per session; a reconnect asks again.
                self._consented = False
            backoff = next_backoff(backoff, time.monotonic() - started)
            log.info("reconnecting in %.0fs", backoff)
            if self.tray:
                self.tray.set_state(IDLE, "Reconnecting…")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass

    async def _run_once(self) -> None:
        log.info("connecting to %s", self.endpoint.split("?")[0])
        async with websockets.connect(self.endpoint, max_size=None, ping_interval=20) as socket:
            self._socket = socket
            info = sysinfo.collect()
            await socket.send(
                json.dumps(
                    {
                        "host_name": info["hostname"],
                        "system_info": info,
                        "monitors": self.capture.monitors,
                        "agent_version": __version__,
                        "privacy_mode": privacy.supported_mode(),
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

            choice = "once"
            by = "endpoint user"
            if self.standing_consent:
                log.info("starting under the permission given when this computer was enrolled")
                by = "standing permission"
            elif can_resume(self._streamed_until, time.monotonic()):
                log.info("reconnected during a consented session; continuing without asking again")
            else:
                choice = await asyncio.to_thread(
                    ask_consent_choice, self.code, None, 120.0, self.auto_consent,
                    self.standing_allowed,
                )
            granted = choice != "deny"
            await socket.send(json.dumps({"type": "consent", "granted": granted, "by": by}))

            if choice == "always" and self.on_standing is not None:
                await self._enrol()

            if not granted:
                log.info("consent denied; nothing will be captured")
                self._streamed_until = None
                self._over()
                if self.tray:
                    self.tray.set_state(IDLE, "Session denied")
                    self.tray.notify("You denied the session. Nothing was shared.", "Session denied")
                self._stop.set()
                return

            self._consented = True
            self._tiles.request_keyframe()
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
                self._streamed_until = time.monotonic()
                receiver.cancel()
                self._close_tools()
                if self.tray:
                    self.tray.set_state(IDLE, "Not in a session")
                    self.tray.notify("The remote session has ended.", "Session ended")

    async def _stream(self, socket) -> None:
        while not self._stop.is_set():
            started = asyncio.get_running_loop().time()
            image = await asyncio.to_thread(self.capture.grab)
            payload = await asyncio.to_thread(self._tiles.encode, image, self.rate.quality)
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
            # This loop is the whole control channel for the session - input,
            # terminal, files, clipboard, monitor switching, and the "end"
            # message itself. It runs as a detached task whose exception is
            # never awaited or retrieved, so one malformed/unexpected message
            # (a non-integer "index"/"cols"/"rows", an edge case a handler
            # does not expect) used to end this loop for good: everything
            # above would go silently, permanently deaf for the rest of the
            # connection - frames kept streaming obliviously, and the
            # operator could not even cleanly end the session. The agent
            # looked dead; it was actually just deaf.
            try:
                if kind == "input":
                    self.injector.apply(message, self.capture.geometry)
                elif kind == "monitor":
                    self.capture.select(int(message.get("index", 0)))
                elif kind == "keyframe":
                    self._tiles.request_keyframe()
                elif kind == "blank":
                    await self._handle_blank(message)
                elif kind == "terminal":
                    await self._handle_terminal(message)
                elif kind == "files":
                    await self._handle_files(message)
                elif kind == "clipboard":
                    await self._handle_clipboard(message)
                elif kind == "end":
                    log.info("the operator ended the session")
                    self._stop.set()
                    return
            except Exception as exc:
                log.warning("could not handle a %r message: %s", kind, exc)

    # ---------------------------------------------------------------- tools

    async def _send(self, payload: dict) -> None:
        if self._socket is not None:
            try:
                await self._socket.send(json.dumps(payload))
            except Exception as exc:
                log.debug("could not send %s: %s", payload.get("type"), exc)

    def _close_tools(self) -> None:
        # A blank left up after the session ends would strand the person at the
        # keyboard behind a black screen they cannot dismiss.
        if self._privacy.active:
            log.warning("session ended while blanked; releasing the privacy blank")
            self._privacy.disable()
        if self._terminal is not None:
            self._terminal.close()
            self._terminal = None
        for upload in self._uploads.values():
            upload.abort()
        self._uploads.clear()
        # A connection that drops between a mouse/key down and its matching
        # up left that button or key physically stuck at the OS level with no
        # code path that ever released it - see InputInjector.release_all.
        self.injector.release_all()

    async def _handle_terminal(self, message: dict) -> None:
        action = message.get("action")
        loop = asyncio.get_running_loop()

        if action == "open":
            if self._terminal is None:
                def on_output(text: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        self._send({"type": "terminal", "action": "output", "data": text}), loop
                    )

                self._terminal = RemoteTerminal(on_output, loop)
            self._terminal.open(int(message.get("cols", 100)), int(message.get("rows", 30)))
            await self._send(
                {"type": "terminal", "action": "opened", "shell": " ".join(default_shell())}
            )
        elif action == "input" and self._terminal is not None:
            self._terminal.write(str(message.get("data", "")))
        elif action == "resize" and self._terminal is not None:
            self._terminal.resize(int(message.get("cols", 100)), int(message.get("rows", 30)))
        elif action == "close":
            if self._terminal is not None:
                self._terminal.close()
                self._terminal = None
            await self._send({"type": "terminal", "action": "closed"})

    async def _handle_files(self, message: dict) -> None:
        action = message.get("action")

        if action == "list":
            result = await asyncio.to_thread(files.listing, message.get("path"))
            await self._send({"type": "files", "action": "list", **result})

        elif action == "get":
            path = str(message.get("path", ""))
            name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            try:
                for chunk, final in files.read_chunks(path):
                    await self._send({"type": "files", "action": "chunk", "name": name,
                                      "data": chunk, "final": final})
                    await asyncio.sleep(0)
                log.info("sent %s to the operator", path)
            except OSError as exc:
                await self._send({"type": "files", "action": "error",
                                  "path": path, "error": str(exc)})

        elif action == "put":
            path = str(message.get("path", ""))
            try:
                upload = self._uploads.get(path)
                if upload is None:
                    upload = files.Upload(path)
                    self._uploads[path] = upload
                if message.get("data"):
                    upload.write(str(message["data"]))
                if message.get("final"):
                    done = upload.finish()
                    self._uploads.pop(path, None)
                    await self._send({"type": "files", "action": "received", **done})
            except (OSError, ValueError) as exc:
                stale = self._uploads.pop(path, None)
                if stale is not None:
                    stale.abort()
                await self._send({"type": "files", "action": "error",
                                  "path": path, "error": str(exc)})

    async def _handle_clipboard(self, message: dict) -> None:
        action = message.get("action")
        if action == "get":
            text = await asyncio.to_thread(clipboard.get_text)
            await self._send({"type": "clipboard", "action": "text", "text": text or ""})
        elif action == "set":
            ok = await asyncio.to_thread(clipboard.set_text, str(message.get("text", "")))
            await self._send({"type": "clipboard", "action": "set", "ok": ok})

    async def _handle_blank(self, message: dict) -> None:
        wanted = bool(message.get("on"))
        if wanted:
            state = await asyncio.to_thread(self._privacy.enable, self._blank_blocks_input)
            if self.tray and state.get("active"):
                self.tray.notify(
                    "Your screen has been blanked for privacy."
                    if state["mode"] == privacy.MODE_EXCLUDED
                    else "Your screen is locked while the session continues.",
                    "Privacy blank on",
                )
        else:
            state = await asyncio.to_thread(self._privacy.disable)
            if self.tray:
                self.tray.notify("Your screen is visible again.", "Privacy blank off")

        await self._send({"type": "blank", "action": "state", **state})
