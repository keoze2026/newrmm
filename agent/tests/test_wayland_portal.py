"""The Wayland XDG-portal path for capture and input.

No CI runner (and no dev machine building this) has a real Wayland
compositor with a portal backend answering on the session bus, so what is
actually testable here is the contract every caller depends on: with no
portal/PyGObject/GStreamer available, every piece degrades to "unavailable"
cleanly, never raises, and ScreenCapture/InputInjector fall back to their
ordinary paths exactly as if no portal had been passed at all. The real
handshake (CreateSession/SelectSources/Start/OpenPipeWireRemote) can only be
exercised against a real compositor, by hand, on Linux.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmm_agent import wayland_portal  # noqa: E402
from rmm_agent.capture import ScreenCapture  # noqa: E402
from rmm_agent.remote_input import InputInjector  # noqa: E402


def test_keysym_for_known_names_matches_x11_keysymdef():
    assert wayland_portal.keysym_for("Enter") == 0xFF0D
    assert wayland_portal.keysym_for("Escape") == 0xFF1B
    assert wayland_portal.keysym_for("F1") == 0xFFBE


def test_keysym_for_printable_ascii_is_its_own_code_point():
    assert wayland_portal.keysym_for("a") == ord("a")
    assert wayland_portal.keysym_for("7") == ord("7")


def test_keysym_for_unknown_multichar_name_is_none():
    assert wayland_portal.keysym_for("Unidentified") is None


def test_session_is_wayland_reads_the_env_var(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert wayland_portal.session_is_wayland() is False
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert wayland_portal.session_is_wayland() is True


def test_portal_session_degrades_cleanly_with_no_backend():
    """On this runner there is no PyGObject, or there is PyGObject but no
    portal answering on the bus - either way this must report unavailable,
    not raise."""
    session = wayland_portal.PortalSession()
    assert session.available in (True, False)
    if not session.available:
        assert session.start() is False
        # Notify* calls on a session that never started must be no-ops, not
        # crashes - a caller cannot always know whether start() succeeded
        # before release_all() fires during teardown.
        session.notify_pointer_button(wayland_portal.BTN_LEFT, True)
        session.notify_keyboard_keysym(wayland_portal.KEYSYMS["Enter"], True)
        session.close()


def test_screen_capture_falls_back_when_the_portal_is_unavailable():
    portal = wayland_portal.PortalSession()
    capture = ScreenCapture(synthetic=False, portal=portal)
    try:
        assert capture.backend != "wayland-portal" or portal.available
        image = capture.grab()
        assert image.size[0] > 0 and image.size[1] > 0
    finally:
        capture.close()


def test_input_injector_falls_back_when_the_portal_is_unavailable():
    portal = wayland_portal.PortalSession()
    injector = InputInjector(enabled=True, portal=portal)
    if not portal.available:
        assert injector._portal is None
