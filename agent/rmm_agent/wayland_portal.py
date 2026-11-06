"""Screen share and remote input on Linux Wayland, through the XDG desktop
portal (org.freedesktop.portal.ScreenCast + org.freedesktop.portal.RemoteDesktop).

Wayland compositors do not let any process read the screen or inject input
directly - that is the whole point of Wayland's security model, and exactly
why the X11 module (rmm_capture_linux.c) and pynput's XTest backend both do
nothing there. The portal is the one door every compositor (GNOME, KDE, ...)
agreed to open: an app asks for it, the *compositor* shows its own picker/
permission dialog, and only after the person approves does the app get a
PipeWire video stream and permission to call the RemoteDesktop "Notify*"
methods. This is unavoidable - it is not an API this agent chose, it is the
only API Wayland offers for this at all.

One combined session covers both halves (capture and input) because
RemoteDesktop's Notify* calls are scoped to a session that also has an active
ScreenCast stream; asking for them separately would show two separate
permission prompts and still need the two session handles reconciled.

Needs PyGObject (`python3-gi`) and, for actually decoding frames out of the
PipeWire stream, GStreamer's pipewire plugin (`gstreamer1.0-pipewire` /
`gst-plugin-pipewire`). Neither is a hard dependency of the agent as a whole -
exactly like the native capture modules, this degrades to "unavailable" and
logs why, rather than failing the whole agent, when either is missing.
"""
import logging
import threading

log = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"

# org.freedesktop.portal.ScreenCast SourceType / CursorMode bitmasks.
SOURCE_TYPE_MONITOR = 1
CURSOR_MODE_EMBEDDED = 2  # the compositor draws the cursor into the frame itself

# org.freedesktop.portal.RemoteDesktop DeviceType bitmask.
DEVICE_KEYBOARD = 1
DEVICE_POINTER = 2

# Linux evdev button codes (linux/input-event-codes.h) - what
# NotifyPointerButton expects, not a browser/X11 button number.
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

# X11 keysyms (X11/keysymdef.h). NotifyKeyboardKeysym takes a keysym, not an
# evdev keycode, which is why this table mirrors remote_input.py's _special()
# almost exactly instead of needing a keymap: printable ASCII already equals
# its own keysym value.
KEYSYMS = {
    "Enter": 0xFF0D, "Backspace": 0xFF08, "Tab": 0xFF09, "Escape": 0xFF1B,
    "Delete": 0xFFFF, "Home": 0xFF50, "End": 0xFF57,
    "PageUp": 0xFF55, "PageDown": 0xFF56,
    "ArrowUp": 0xFF52, "ArrowDown": 0xFF54, "ArrowLeft": 0xFF51, "ArrowRight": 0xFF53,
    "Shift": 0xFFE1, "Control": 0xFFE3, "Alt": 0xFFE9, "Meta": 0xFFEB,
    "CapsLock": 0xFFE5, " ": 0x0020,
    "F1": 0xFFBE, "F2": 0xFFBF, "F3": 0xFFC0, "F4": 0xFFC1,
    "F5": 0xFFC2, "F6": 0xFFC3, "F7": 0xFFC4, "F8": 0xFFC5,
    "F9": 0xFFC6, "F10": 0xFFC7, "F11": 0xFFC8, "F12": 0xFFC9,
}

_PRESSED = 1
_RELEASED = 0


def keysym_for(name: str) -> int | None:
    """Browser key name -> X11 keysym, for NotifyKeyboardKeysym."""
    if name in KEYSYMS:
        return KEYSYMS[name]
    if len(name) == 1:
        return ord(name)
    return None


class PortalSession:
    """One combined ScreenCast + RemoteDesktop portal session.

    Every method here blocks the calling thread until the portal backend
    replies - including, the first time, however long it takes the person to
    answer the compositor's own permission/picker dialog. That is deliberate:
    callers (ScreenCapture, InputInjector) already construct synchronously at
    session start, the same point X11's open() blocks briefly on the X
    connection.
    """

    def __init__(self) -> None:
        self.available = False
        self.session_handle: str | None = None
        self.node_id: int | None = None
        self.pipewire_fd: int | None = None
        self.monitors: list[dict] = []
        self._bus = None
        self._context = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._sender_token = ""
        self._token_counter = 0
        self._lock = threading.Lock()

        try:
            import gi

            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except Exception as exc:
            log.info("PyGObject not installed; the Wayland portal path is unavailable (%s)", exc)
            return

        self._Gio = Gio
        self._GLib = GLib

        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            # The Request object path the portal replies on is predictable
            # from the caller's own unique bus name (":1.42" -> "1_42"), per
            # the portal spec - this lets us subscribe *before* calling, so
            # there is no window where a fast reply could arrive unheard.
            self._sender_token = self._bus.get_unique_name().lstrip(":").replace(".", "_")
        except Exception as exc:
            log.info("could not reach the session D-Bus; Wayland portal unavailable (%s)", exc)
            self._bus = None
            return

        # Signal delivery needs a pumped GLib main context; nothing else in
        # this process runs one (session.py is asyncio, not GLib), so this
        # owns a dedicated context/thread for its whole lifetime rather than
        # fighting over the global default one.
        self._context = GLib.MainContext.new()
        self._loop = GLib.MainLoop.new(self._context, False)
        self._thread = threading.Thread(target=self._run_loop, name="wayland-portal", daemon=True)
        self._thread.start()
        self.available = True

    def _run_loop(self) -> None:
        self._context.push_thread_default()
        try:
            self._loop.run()
        finally:
            self._context.pop_thread_default()

    def _next_token(self, prefix: str) -> str:
        with self._lock:
            self._token_counter += 1
            return f"rmm_{prefix}_{self._token_counter}"

    def _await_request(self, handle_path: str, timeout: float) -> dict:
        """Block until the Request at `handle_path` emits its Response
        signal, and return its results dict. Raises on refusal or timeout."""
        GLib = self._GLib
        event = threading.Event()
        outcome: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, parameters) -> None:
            code, results = parameters.unpack()
            outcome["code"] = code
            outcome["results"] = results
            event.set()

        sub_id = self._bus.signal_subscribe(
            None, REQUEST_IFACE, "Response", handle_path, None,
            self._Gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            if not event.wait(timeout):
                raise TimeoutError("the portal did not respond in time")
        finally:
            self._bus.signal_unsubscribe(sub_id)

        if outcome.get("code") != 0:
            # 1 = the person cancelled/declined; 2 = the backend ended it.
            raise PermissionError(f"the portal request was not approved (code {outcome.get('code')})")
        return outcome.get("results") or {}

    def _call(self, iface: str, method: str, variant, reply_signature: str):
        GLib = self._GLib
        return self._bus.call_sync(
            PORTAL_BUS, PORTAL_PATH, iface, method, variant,
            GLib.VariantType.new(reply_signature),
            self._Gio.DBusCallFlags.NONE, -1, None,
        )

    def _call_request(self, iface: str, method: str, variant, timeout: float = 120.0) -> dict:
        """Call a portal method whose OUT is a Request object path (`o`), and
        wait for that Request's Response. `timeout` is generous because the
        first call of each kind is answered by a *person*, not the backend."""
        GLib = self._GLib
        token = self._next_token(method)
        handle_path = f"/org/freedesktop/portal/desktop/request/{self._sender_token}/{token}"

        # Subscribing before the call closes the race where a reply lands
        # before a subscription made afterward could ever see it.
        event_box: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, parameters) -> None:
            code, results = parameters.unpack()
            event_box["code"] = code
            event_box["results"] = results
            event_box["event"].set()

        waiter = threading.Event()
        event_box["event"] = waiter
        sub_id = self._bus.signal_subscribe(
            None, REQUEST_IFACE, "Response", handle_path, None,
            self._Gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            reply = self._call(iface, method, variant, "(o)")
            actual_path = reply.unpack()[0]
            if actual_path != handle_path:
                # The portal spec allows this only on a token collision,
                # which _next_token's monotonic counter should never hit -
                # but if it ever does, resubscribe on the path actually used
                # rather than silently waiting on the wrong one forever.
                self._bus.signal_unsubscribe(sub_id)
                sub_id = self._bus.signal_subscribe(
                    None, REQUEST_IFACE, "Response", actual_path, None,
                    self._Gio.DBusSignalFlags.NONE, on_response,
                )
            if not waiter.wait(timeout):
                raise TimeoutError(f"the portal did not answer {method} in time")
        finally:
            self._bus.signal_unsubscribe(sub_id)

        if event_box.get("code") != 0:
            raise PermissionError(f"{method} was not approved (code {event_box.get('code')})")
        return event_box.get("results") or {}

    def start(self, want_input: bool = True) -> bool:
        """Run the whole handshake: create one session, ask for a monitor
        share and (optionally) keyboard/pointer, then open the PipeWire
        stream. This is the call that pops the compositor's own picker/
        permission dialog. Returns False (never raises) on any failure, so a
        Wayland box with no working portal just falls back to mss like any
        other capture failure."""
        if not self.available:
            return False
        GLib = self._GLib
        try:
            session_token = self._next_token("session")
            options = GLib.Variant("a{sv}", {"session_handle_token": GLib.Variant("s", session_token)})
            create_iface = REMOTE_DESKTOP_IFACE if want_input else SCREENCAST_IFACE
            results = self._call_request(
                create_iface, "CreateSession", GLib.Variant("(a{sv})", (options,))
            )
            self.session_handle = results.get("session_handle")
            if not self.session_handle:
                raise RuntimeError("CreateSession returned no session_handle")

            if want_input:
                device_options = GLib.Variant(
                    "a{sv}", {"types": GLib.Variant("u", DEVICE_KEYBOARD | DEVICE_POINTER)}
                )
                self._call_request(
                    REMOTE_DESKTOP_IFACE, "SelectDevices",
                    GLib.Variant("(oa{sv})", (self.session_handle, device_options)),
                )

            source_options = GLib.Variant(
                "a{sv}",
                {
                    "types": GLib.Variant("u", SOURCE_TYPE_MONITOR),
                    "multiple": GLib.Variant("b", False),
                    "cursor_mode": GLib.Variant("u", CURSOR_MODE_EMBEDDED),
                },
            )
            self._call_request(
                SCREENCAST_IFACE, "SelectSources",
                GLib.Variant("(oa{sv})", (self.session_handle, source_options)),
            )

            start_iface = REMOTE_DESKTOP_IFACE if want_input else SCREENCAST_IFACE
            start_results = self._call_request(
                start_iface, "Start",
                GLib.Variant("(osa{sv})", (self.session_handle, "", GLib.Variant("a{sv}", {}))),
            )
            streams = start_results.get("streams") or []
            if not streams:
                raise RuntimeError("Start() returned no screen-cast stream")
            self._apply_streams(streams)

            pipewire_reply, fd_list = self._bus.call_with_unix_fd_list_sync(
                PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE, "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (self.session_handle, GLib.Variant("a{sv}", {}))),
                GLib.VariantType.new("(h)"),
                self._Gio.DBusCallFlags.NONE, -1, None, None,
            )
            fd_index = pipewire_reply.unpack()[0]
            self.pipewire_fd = fd_list.get(fd_index)
            log.info(
                "Wayland portal session started: node=%s monitors=%d",
                self.node_id, len(self.monitors),
            )
            return True
        except Exception as exc:
            log.warning("could not start the Wayland portal session: %s", exc)
            self.close()
            return False

    def _apply_streams(self, streams) -> None:
        self.monitors = []
        for i, (node_id, props) in enumerate(streams):
            if self.node_id is None:
                self.node_id = node_id
            size = props.get("size")
            position = props.get("position")
            width, height = (size if size else (1920, 1080))
            left, top = (position if position else (0, 0))
            self.monitors.append(
                {"index": i, "label": f"Monitor {i + 1}", "width": int(width),
                 "height": int(height), "left": int(left), "top": int(top)}
            )

    # ------------------------------------------------------------- input
    # Every Notify* call is fire-and-forget (no reply to wait for beyond the
    # ordinary D-Bus method return), unlike Start()/CreateSession(), so these
    # never touch the Request/Response machinery above.

    def notify_pointer_motion_absolute(self, x: float, y: float) -> None:
        if not self.available or self.node_id is None:
            return
        GLib = self._GLib
        try:
            self._bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, REMOTE_DESKTOP_IFACE, "NotifyPointerMotionAbsolute",
                GLib.Variant(
                    "(oa{sv}udd)",
                    (self.session_handle, {}, self.node_id, float(x), float(y)),
                ),
                None, self._Gio.DBusCallFlags.NONE, -1, None,
            )
        except Exception as exc:
            log.debug("NotifyPointerMotionAbsolute failed: %s", exc)

    def notify_pointer_button(self, button: int, pressed: bool) -> None:
        if not self.available:
            return
        GLib = self._GLib
        try:
            self._bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, REMOTE_DESKTOP_IFACE, "NotifyPointerButton",
                GLib.Variant(
                    "(oa{sv}iu)",
                    (self.session_handle, {}, button, _PRESSED if pressed else _RELEASED),
                ),
                None, self._Gio.DBusCallFlags.NONE, -1, None,
            )
        except Exception as exc:
            log.debug("NotifyPointerButton failed: %s", exc)

    def notify_pointer_axis_discrete(self, vertical: bool, steps: int) -> None:
        if not self.available or steps == 0:
            return
        GLib = self._GLib
        try:
            self._bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, REMOTE_DESKTOP_IFACE, "NotifyPointerAxisDiscrete",
                GLib.Variant(
                    "(oa{sv}ui)", (self.session_handle, {}, 0 if vertical else 1, int(steps)),
                ),
                None, self._Gio.DBusCallFlags.NONE, -1, None,
            )
        except Exception as exc:
            log.debug("NotifyPointerAxisDiscrete failed: %s", exc)

    def notify_keyboard_keysym(self, keysym: int, pressed: bool) -> None:
        if not self.available:
            return
        GLib = self._GLib
        try:
            self._bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, REMOTE_DESKTOP_IFACE, "NotifyKeyboardKeysym",
                GLib.Variant(
                    "(oa{sv}iu)",
                    (self.session_handle, {}, int(keysym), _PRESSED if pressed else _RELEASED),
                ),
                None, self._Gio.DBusCallFlags.NONE, -1, None,
            )
        except Exception as exc:
            log.debug("NotifyKeyboardKeysym failed: %s", exc)

    def close(self) -> None:
        if self.session_handle and self._bus is not None:
            try:
                self._bus.call_sync(
                    PORTAL_BUS, self.session_handle, SESSION_IFACE, "Close",
                    None, None, self._Gio.DBusCallFlags.NONE, -1, None,
                )
            except Exception as exc:
                log.debug("portal Session.Close failed: %s", exc)
        self.session_handle = None
        if self._loop is not None:
            self._loop.quit()


def session_is_wayland() -> bool:
    import os

    return bool(os.environ.get("WAYLAND_DISPLAY"))
