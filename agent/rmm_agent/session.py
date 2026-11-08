"""The session client: attach, ask for consent, then stream and take input."""
import asyncio
import json
import logging
import time

import websockets

from rmm_agent import __version__, clipboard, files, platform_support, privacy, sysinfo
from rmm_agent.capture import RateController, ScreenCapture
from rmm_agent.chat import ChatWindow
from rmm_agent.consent import ask_choice as ask_consent_choice
from rmm_agent.remote_input import InputInjector
from rmm_agent.terminal import RemoteTerminal, default_shell
from rmm_agent.tiles import TileEncoder
from rmm_agent.tray import CONNECTED, IDLE, SHARING, Tray
from rmm_agent import guest_token, wayland_portal

log = logging.getLogger(__name__)

# Spec section 8: the agent reconnects automatically after drops.
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
# A connection that lasted this long was a working one; a shorter one means the
# relay or this machine is turning it away, so the delay must keep growing.
HEALTHY_SECONDS = 30.0
# Retrying cannot fix these: the session ended (4404), consent was refused
# (4403), or the credentials were rejected (4401: wrong device secret, or the
# session belongs to another computer).
GIVE_UP_CODES = (4401, 4403, 4404)
# How long to wait for the relay's "welcome" after the hello. A relay older
# than the welcome never sends one; the session still works, just unbound.
WELCOME_SECONDS = 3.0
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
        fps: int = 30,
        quality: int = 60,
        budget_kbps: int = 0,
        synthetic: bool = False,
        inject: bool = True,
        auto_consent: bool = False,
        on_over=None,
        standing_allowed: bool = False,
        on_standing=None,
        on_enrolled=None,
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
        # On Wayland neither X11 capture nor XTest input can see the real
        # desktop; the only door is the XDG portal (wayland_portal). It is
        # opened per connection, only AFTER the person consents - the
        # compositor's own dialog and its "screen is being shared" indicator
        # must never appear before that - and closed when the connection ends.
        self._inject = inject
        self._wayland = (
            not synthetic and platform_support.LINUX and wayland_portal.session_is_wayland()
        )
        self._portal: wayland_portal.PortalSession | None = None
        # Lets a reconnect (and, for an enrolled device, the next session)
        # reuse the person's approval instead of showing the dialog again.
        self._restore_token: str | None = None
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
        # Fired the moment enrolment succeeds, not at session end: the device's
        # standing-presence socket can then start right away, in parallel with
        # this still-running session, instead of only after it ends - closing
        # the window where a push from the relay to "start sharing" has no
        # device socket listening yet to receive it (hub.to_device_json falls
        # back to a Redis publish with no queueing, so that push is lost, not
        # delayed, if nothing is subscribed at that instant).
        self.on_enrolled = on_enrolled
        self.enrolled = False
        # A session an enrolled device starts because an operator opened it: no
        # window, because the person gave permission once; it ends when the
        # connection does, and the operator opening it again starts a new one.
        self.standing_consent = standing_consent
        self.single_shot = single_shot
        self._consented = False
        self._streamed_until: float | None = None
        self._terminal: RemoteTerminal | None = None
        self._chat: ChatWindow | None = None
        self._privacy = privacy.PrivacyBlank(
            watchdog_seconds=blank_watchdog, on_release=self._blank_released
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        # Changed-region streaming (specification section 10).
        self._tiles = TileEncoder()
        self._blank_blocks_input = blank_blocks_input
        self._uploads: dict[str, files.Upload] = {}
        self._socket = None

    def _blank_released(self, reason: str, state: dict) -> None:
        """The blank ended at the endpoint (watchdog or Escape): tell the
        operator, whose console would otherwise keep saying "blanked"."""
        log.info("privacy blank released at the endpoint (%s)", reason)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        payload = {"type": "blank", "action": "state", **state, "released_by": reason}
        asyncio.run_coroutine_threadsafe(self._send(payload), loop)
        if self.tray:
            self.tray.notify("Your screen is visible again.", "Privacy blank off")

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
            if self.on_enrolled is not None:
                try:
                    self.on_enrolled()
                except Exception as exc:
                    log.warning("could not start standing presence alongside this session: %s", exc)
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
        """The session URL. Credentials go in the hello, never in the URL,
        because URLs are written to the reverse proxy's access log."""
        return f"{self.relay_url}/ws/guest/{self.code}"

    def _legacy_endpoint(self) -> str:
        """The URL form a relay older than hello-credentials insists on."""
        from urllib.parse import quote

        return (
            f"{self.endpoint}?device_id={quote(self.device_id)}"
            f"&secret={quote(self.device_secret)}"
        )

    async def _connect(self):
        """Open the session socket; returns (context manager, socket)."""
        options = {"max_size": None, "ping_interval": 20}
        connection = websockets.connect(self.endpoint, **options)
        try:
            return connection, await connection.__aenter__()
        except websockets.InvalidStatus as exc:
            # An older relay checks device credentials in the URL before the
            # handshake and refuses it with 403 when they are not there.
            if not (self.device_id and self.device_secret) or exc.response.status_code != 403:
                raise
            log.info("this relay wants the device credentials in the URL; using that")
            connection = websockets.connect(self._legacy_endpoint(), **options)
            return connection, await connection.__aenter__()

    def _hello(self, info: dict) -> dict:
        hello = {
            "host_name": info["hostname"],
            "system_info": info,
            "monitors": self.capture.monitors,
            "agent_version": __version__,
            "privacy_mode": privacy.supported_mode(),
            # This agent keeps the secret the relay binds the session with.
            "token_aware": True,
        }
        token = guest_token.load(self.code)
        if token:
            hello["guest_token"] = token
        if self.device_id and self.device_secret:
            hello["device_id"] = self.device_id
            hello["secret"] = self.device_secret
        return hello

    async def _await_welcome(self, socket) -> None:
        """Read the relay's welcome and keep the session secret it hands over."""
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=WELCOME_SECONDS)
        except asyncio.TimeoutError:
            log.info("this relay sends no welcome; the session is not bound to this computer")
            return
        if isinstance(raw, bytes):
            return
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if message.get("type") != "welcome":
            # Only an older relay sends anything else first, and nothing it
            # sends before consent needs acting on (a keyframe is requested
            # again when streaming starts).
            return
        token = message.get("guest_token")
        if token:
            guest_token.save(self.code, str(token))
            log.info("this computer is now bound to session %s", self.code)

    async def run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
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
        self._loop = asyncio.get_running_loop()
        log.info("connecting to %s", self.endpoint)
        connection, socket = await self._connect()
        try:
            await self._session(socket)
        except BaseException as exc:
            if not await connection.__aexit__(type(exc), exc, exc.__traceback__):
                raise
        else:
            await connection.__aexit__(None, None, None)

    async def _session(self, socket) -> None:
        self._socket = socket
        info = sysinfo.collect()
        await socket.send(json.dumps(self._hello(info)))
        await self._await_welcome(socket)
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
        if self._wayland:
            await self._open_portal()
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
            await self._close_portal()
            if self.tray:
                self.tray.set_state(IDLE, "Not in a session")
                self.tray.notify("The remote session has ended.", "Session ended")

    async def _open_portal(self) -> None:
        """Wayland: ask the compositor for the screen and input. Runs after
        consent. Blocks (off the event loop) while the person answers the
        compositor's dialog; an enrolled device keeps the approval so later
        sessions start without it."""
        token = self._restore_token
        if token is None and self.standing_consent:
            token = wayland_portal.load_restore_token()
        # 2 = keep the approval until revoked (enrolled device); 1 = while
        # this agent runs (reconnects within an attended session).
        persist = 2 if self.standing_consent else 1
        portal = wayland_portal.PortalSession()
        if self.tray:
            self.tray.set_state(CONNECTED, "Choose the screen to share")
        try:
            ok = await asyncio.to_thread(portal.start, self._inject, token, persist)
        except BaseException:
            # Stopped while the dialog was up: never leave the helper behind.
            portal.close()
            raise
        if not ok or not self.capture.attach_portal(portal):
            await asyncio.to_thread(portal.close)
            log.error(
                "Wayland screen share unavailable (%s). Without it a Wayland "
                "desktop cannot be seen or controlled. Run `rmm-agent status` "
                "to check python3-gi and the GStreamer pipewire plugin.",
                portal.error or "the portal share could not be used",
            )
            if self.tray:
                self.tray.notify(
                    "The screen could not be shared on this Wayland desktop. "
                    + ("You declined the screen share." if portal.denied
                       else "Run 'rmm-agent status' for details."),
                    "Screen share failed",
                )
            return
        self._portal = portal
        if portal.input_available:
            self.injector = InputInjector(enabled=self._inject, portal=portal)
        else:
            log.warning("this desktop's portal shares the screen without remote control")
        if portal.restore_token:
            self._restore_token = portal.restore_token
            if self.standing_consent:
                await asyncio.to_thread(wayland_portal.save_restore_token, portal.restore_token)

    async def _close_portal(self) -> None:
        """End the Wayland share with the connection: no capture outside a
        live, consented session."""
        portal, self._portal = self._portal, None
        if portal is None:
            return
        self.capture.detach_portal()
        self.injector = InputInjector(enabled=self._inject)
        await asyncio.to_thread(portal.close)
        log.info("Wayland screen share closed")

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
                elif kind == "chat":
                    await self._handle_chat(message)
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
        if self._chat is not None:
            self._chat.close()
            self._chat = None
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

    async def _handle_chat(self, message: dict) -> None:
        if message.get("action") != "message":
            return
        text = str(message.get("text", "")).strip()
        if not text:
            return
        loop = asyncio.get_running_loop()
        if self._chat is None:
            def on_reply(reply_text: str) -> None:
                asyncio.run_coroutine_threadsafe(
                    self._send({"type": "chat", "action": "message", "text": reply_text}), loop
                )

            # Off the event loop: starting the GUI thread the first time can
            # take a moment, and frames and input must not wait for it.
            self._chat = await asyncio.to_thread(ChatWindow, on_reply)
        self._chat.receive(text)

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
