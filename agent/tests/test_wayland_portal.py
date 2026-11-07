"""The Wayland path: portal handshake, frames, input, and how a session uses it.

The handshake tests run the real helper (rmm_agent/wayland_helper.py) under
the system python3 against tests/fake_portal.py on a PRIVATE D-Bus bus, so the
real D-Bus calls, Request/Response signals and file-descriptor passing are all
exercised - and nothing ever reaches this machine's real portal or desktop.
GStreamer's test source stands in for PipeWire (the only part a real
compositor is still needed for), at width 1366, where RGB rows are padded.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmm_agent import wayland_portal  # noqa: E402
from rmm_agent.capture import ScreenCapture  # noqa: E402
from rmm_agent.remote_input import InputInjector, _held_variant, scroll_steps  # noqa: E402

HERE = Path(__file__).resolve().parent
SYSTEM_PYTHON = "/usr/bin/python3"


def _system_has_gstreamer() -> bool:
    if not (os.access(SYSTEM_PYTHON, os.X_OK) and shutil.which("dbus-daemon")):
        return False
    probe = (
        "import gi; gi.require_version('Gst','1.0'); from gi.repository import Gst, Gio;"
        "Gst.init(None); assert Gst.ElementFactory.find('videotestsrc')"
    )
    return subprocess.run([SYSTEM_PYTHON, "-c", probe], capture_output=True).returncode == 0


needs_portal_stack = pytest.mark.skipif(
    not _system_has_gstreamer(),
    reason="needs dbus-daemon and the system python3 with PyGObject + GStreamer",
)


@pytest.fixture
def fake_portal(tmp_path, monkeypatch):
    """A private session bus with the fake portal on it. Yields a function
    that starts the fake with extra environment, and the call log path."""
    bus = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1", "--nopidfile"],
        stdout=subprocess.PIPE, text=True,
    )
    address = bus.stdout.readline().strip()
    log_path = tmp_path / "portal.log"
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("RMM_SYSTEM_PYTHON", SYSTEM_PYTHON)
    monkeypatch.setenv(
        "RMM_WAYLAND_TEST_SOURCE",
        "videotestsrc pattern=smpte is-live=true ! video/x-raw,width=1366,height=768,framerate=30/1",
    )
    started = []

    def start(**extra):
        env = dict(os.environ, FAKE_PORTAL_LOG=str(log_path), **extra)
        proc = subprocess.Popen([SYSTEM_PYTHON, "-I", str(HERE / "fake_portal.py")],
                                stdout=subprocess.PIPE, text=True, env=env)
        assert proc.stdout.readline().strip() == "ready"
        started.append(proc)
        return log_path

    yield start
    for proc in started:
        proc.terminate()
        proc.wait(timeout=5)
    bus.terminate()
    bus.wait(timeout=5)


def calls(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


# ------------------------------------------------------------------ handshake


@needs_portal_stack
def test_the_full_portal_handshake_shares_the_screen_and_takes_input(fake_portal):
    log_path = fake_portal()
    portal = wayland_portal.PortalSession()
    try:
        assert portal.start(want_input=True, restore_token="old-token", persist_mode=2), portal.error
        assert portal.input_available
        assert portal.restore_token == "restore-abc"
        assert portal.monitors == [{"index": 0, "label": "Shared screen", "width": 1366,
                                    "height": 768, "left": 1920, "top": 0}]

        data, width, height = portal.grab()
        assert (width, height) == (1366, 768)
        assert len(data) == 1366 * 768 * 3
        # SMPTE bars are vertical: a column keeps one colour down the top
        # half. Reading padded rows as unpadded shifts each row by 2 bytes,
        # so the colour at a fixed column would drift row by row.
        column = [data[y * 1366 * 3 + 30: y * 1366 * 3 + 33] for y in range(0, 400, 7)]
        assert len(set(column)) == 1

        portal.notify_pointer_motion_absolute(683.0, 384.0)
        portal.notify_pointer_button(wayland_portal.BTN_LEFT, True)
        portal.notify_pointer_button(wayland_portal.BTN_LEFT, False)
        portal.notify_pointer_axis_discrete(True, 2)
        portal.notify_keyboard_keysym(wayland_portal.keysym_for("é"), True)
        portal.grab()  # replies only after the input above was handled
    finally:
        portal.close()

    log = calls(log_path)
    methods = [c["method"] for c in log]
    assert methods[:4] == ["CreateSession", "SelectDevices", "SelectSources", "Start"]
    assert "OpenPipeWireRemote" in methods
    # Every request carries a handle_token, so the reply cannot be missed.
    for call in log:
        if call["method"] in ("CreateSession", "SelectDevices", "SelectSources", "Start"):
            assert "handle_token" in call["args"][-1], call
    devices = next(c for c in log if c["method"] == "SelectDevices")["args"][1]
    assert devices["persist_mode"] == 2 and devices["restore_token"] == "old-token"
    sources = next(c for c in log if c["method"] == "SelectSources")["args"][1]
    assert sources["cursor_mode"] == 2
    motion = next(c for c in log if c["method"] == "NotifyPointerMotionAbsolute")["args"]
    assert motion[2:] == [47, 683.0, 384.0]
    axis = next(c for c in log if c["method"] == "NotifyPointerAxisDiscrete")["args"]
    assert axis[2:] == [0, 2]
    key = next(c for c in log if c["method"] == "NotifyKeyboardKeysym")["args"]
    assert key[2:] == [0x01000000 | ord("é") if ord("é") > 0xFF else ord("é"), 1]
    assert [c["method"] for c in log if c.get("iface") == "Session"] == ["Close"]


@needs_portal_stack
def test_declining_the_compositor_dialog_is_reported_as_declined(fake_portal):
    fake_portal(FAKE_PORTAL_DENY="Start")
    portal = wayland_portal.PortalSession()
    assert portal.start(want_input=True) is False
    assert portal.denied is True
    assert portal.started is False
    with pytest.raises(RuntimeError):
        portal.grab()


@needs_portal_stack
def test_a_portal_without_remote_desktop_still_shares_the_screen(fake_portal):
    """xdg-desktop-portal-wlr and older KDE offer ScreenCast only. A picture
    with no control beats a black screen."""
    log_path = fake_portal(FAKE_PORTAL_NO_REMOTE="1")
    portal = wayland_portal.PortalSession()
    try:
        assert portal.start(want_input=True), portal.error
        assert portal.input_available is False
        assert portal.grab()[1:] == (1366, 768)
        injector = InputInjector(enabled=True, portal=portal)
        assert injector._portal is None
    finally:
        portal.close()
    created = [c for c in calls(log_path) if c["method"] == "CreateSession"]
    assert [c["iface"] for c in created] == ["ScreenCast"]


def test_a_missing_system_python_fails_cleanly(monkeypatch):
    monkeypatch.setenv("RMM_SYSTEM_PYTHON", "/nonexistent/python3")
    portal = wayland_portal.PortalSession()
    assert portal.start() is False
    assert portal.error
    # Teardown on a session that never started must be harmless.
    portal.notify_pointer_button(wayland_portal.BTN_LEFT, True)
    portal.close()


def test_the_helper_never_imports_the_agent():
    """It runs under the system python3, which has no rmm_agent."""
    source = wayland_portal.helper_path().read_text()
    assert "rmm_agent" not in source.split('"""', 2)[2]


# ------------------------------------------------------------------ detection


def test_session_is_wayland_is_not_fooled_by_a_missing_wayland_display(tmp_path):
    assert wayland_portal.session_is_wayland({"WAYLAND_DISPLAY": "wayland-0"})
    assert wayland_portal.session_is_wayland({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"})
    # Started by systemd at login without the desktop's variables: the
    # compositor's socket gives it away.
    (tmp_path / "wayland-0").touch()
    (tmp_path / "wayland-0.lock").touch()
    assert wayland_portal.session_is_wayland({"XDG_RUNTIME_DIR": str(tmp_path)})
    assert not wayland_portal.session_is_wayland({"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"})
    assert not wayland_portal.session_is_wayland({"XDG_RUNTIME_DIR": str(tmp_path / "none")})


def test_keysyms():
    assert wayland_portal.keysym_for("Enter") == 0xFF0D
    assert wayland_portal.keysym_for("a") == ord("a")
    assert wayland_portal.keysym_for("é") == ord("é")  # Latin-1: its own code
    assert wayland_portal.keysym_for("ж") == 0x01000000 | ord("ж")
    assert wayland_portal.keysym_for("Unidentified") is None


# ------------------------------------------------------------------ input


class RecordingPortal:
    started = True
    input_available = True
    monitors = [{"index": 0, "label": "Shared screen", "width": 1366, "height": 768,
                 "left": 1920, "top": 0}]

    def __init__(self):
        self.sent = []

    def notify_pointer_motion_absolute(self, x, y):
        self.sent.append(("motion", x, y))

    def notify_pointer_button(self, button, pressed):
        self.sent.append(("button", button, pressed))

    def notify_pointer_axis_discrete(self, vertical, steps):
        self.sent.append(("axis", steps))

    def notify_keyboard_keysym(self, keysym, pressed):
        self.sent.append(("key", keysym, pressed))

    def grab(self):
        return (b"\x00" * (1366 * 768 * 3), 1366, 768)

    def close(self):
        self.sent.append(("close",))


def test_portal_pointer_moves_in_the_stream_own_space_not_desktop_space():
    """The shared monitor sits at x=1920. The portal wants 0..1366 within
    the stream; adding 1920 sent every move off the screen."""
    portal = RecordingPortal()
    injector = InputInjector(enabled=True, portal=portal)
    injector.apply({"kind": "mouse", "action": "move", "x": 0.5, "y": 0.5}, (1920, 0, 1366, 768))
    assert portal.sent == [("motion", 683.0, 384.0)]


def test_scroll_direction_follows_the_browser():
    assert scroll_steps(0) == 0
    assert scroll_steps(3) == 1        # small downward: down, not up
    assert scroll_steps(-3) == -1
    assert scroll_steps(250) == 2
    assert scroll_steps(-100) == -1
    portal = RecordingPortal()
    injector = InputInjector(enabled=True, portal=portal)
    injector.apply({"kind": "scroll", "dy": 3}, (0, 0, 100, 100))
    injector.apply({"kind": "scroll", "dy": -120}, (0, 0, 100, 100))
    assert portal.sent == [("axis", 1), ("axis", -1)]


def test_releasing_a_letter_after_shift_releases_the_key_that_is_held():
    assert _held_variant("A", {"a"}) == "a"
    assert _held_variant(ord("A"), {ord("a")}) == ord("a")
    portal = RecordingPortal()
    injector = InputInjector(enabled=True, portal=portal)
    injector.apply({"kind": "key", "action": "down", "key": "a"}, (0, 0, 1, 1))
    injector.apply({"kind": "key", "action": "up", "key": "A"}, (0, 0, 1, 1))
    assert portal.sent == [("key", ord("a"), True), ("key", ord("a"), False)]
    assert injector._pressed_keys == set()


# ------------------------------------------------------------------ capture


def test_screen_capture_uses_a_started_portal_and_goes_back_after():
    capture = ScreenCapture(synthetic=True)
    before = (capture.backend, capture.monitors)
    portal = RecordingPortal()
    assert capture.attach_portal(portal)
    assert capture.backend == "wayland-portal"
    assert capture.grab().size == (1366, 768)
    capture.detach_portal()
    assert (capture.backend, capture.monitors) == before


def test_screen_capture_prefers_a_working_portal_over_x11(monkeypatch):
    """Regression (lesson #50): under Wayland the X11 module opens through
    XWayland and returns black frames, so a started portal must win."""
    monkeypatch.setattr(ScreenCapture, "_open_native", lambda self: True)
    capture = ScreenCapture(synthetic=False, portal=RecordingPortal())
    assert capture.backend == "wayland-portal"
    assert capture._native is None


def test_a_portal_that_never_started_is_not_used():
    capture = ScreenCapture(synthetic=True, portal=wayland_portal.PortalSession())
    assert capture.backend == "synthetic"


# ------------------------------------------------------------------ session


def _wayland_session(monkeypatch, portals, **kwargs):
    from rmm_agent import session as session_module

    monkeypatch.setattr(session_module.wayland_portal, "session_is_wayland", lambda: True)
    monkeypatch.setattr(session_module.platform_support, "LINUX", True)
    monkeypatch.setattr(session_module.ScreenCapture, "_open_native", lambda self: False)

    class FakePortalSession(RecordingPortal):
        def __init__(self):
            super().__init__()
            self.error = None
            self.denied = False
            self.restore_token = "restore-xyz"
            self.start_args = None
            portals.append(self)

        def start(self, want_input, token, persist):
            self.start_args = (want_input, token, persist)
            return True

    monkeypatch.setattr(session_module.wayland_portal, "PortalSession", FakePortalSession)
    return session_module.AgentSession("ws://relay.invalid", "ABCD", inject=True, **kwargs)


def test_no_portal_dialog_before_consent_and_none_left_after(monkeypatch):
    """The compositor's dialog and its sharing indicator must not appear
    before the person consents, and the share must end with the session."""
    portals = []
    session = _wayland_session(monkeypatch, portals)
    assert portals == []  # constructing the session asks the compositor nothing

    asyncio.run(session._open_portal())
    assert len(portals) == 1
    assert portals[0].start_args == (True, None, 1)
    assert session.capture.backend == "wayland-portal"
    assert session.injector._portal is portals[0]

    asyncio.run(session._close_portal())
    assert portals[0].sent[-1] == ("close",)
    assert session.capture.backend != "wayland-portal"
    assert session.injector._portal is None


def test_an_enrolled_device_keeps_the_approval_between_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    portals = []
    session = _wayland_session(monkeypatch, portals, standing_consent=True, single_shot=True)
    asyncio.run(session._open_portal())
    asyncio.run(session._close_portal())
    assert portals[0].start_args == (True, None, 2)
    assert wayland_portal.load_restore_token() == "restore-xyz"

    later = _wayland_session(monkeypatch, portals, standing_consent=True, single_shot=True)
    asyncio.run(later._open_portal())
    asyncio.run(later._close_portal())
    assert portals[1].start_args == (True, "restore-xyz", 2)

    wayland_portal.forget_restore_token()
    assert wayland_portal.load_restore_token() is None


def test_a_portal_that_fails_leaves_the_session_on_its_old_path(monkeypatch):
    portals = []
    session = _wayland_session(monkeypatch, portals)
    from rmm_agent import session as session_module

    class Failing(RecordingPortal):
        error = "no portal"
        denied = False
        restore_token = None

        def start(self, *_a):
            return False

    closed = []
    monkeypatch.setattr(session_module.wayland_portal, "PortalSession",
                        lambda: type("F", (Failing,), {"close": lambda self: closed.append(1)})())
    asyncio.run(session._open_portal())
    assert session._portal is None
    assert closed == [1]
    assert session.capture.backend != "wayland-portal"


def test_status_check_reports_what_the_machine_has():
    report = wayland_portal.diagnose()
    assert isinstance(report, dict)
    if os.access(SYSTEM_PYTHON, os.X_OK):
        assert "pygobject" in report or "error" in report


# Keep the helper honest about timing: a grab must not wait the full
# first-frame timeout once frames are flowing.
@needs_portal_stack
def test_grabs_are_fast_once_streaming(fake_portal):
    fake_portal()
    portal = wayland_portal.PortalSession()
    try:
        assert portal.start(want_input=False), portal.error
        started = time.monotonic()
        for _ in range(20):
            portal.grab()
        assert time.monotonic() - started < 5
    finally:
        portal.close()
