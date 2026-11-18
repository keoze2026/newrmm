"""macOS withholds the screen from an app without Screen Recording permission
by handing back a flat redacted fill, so the operator sees a silent grey
picture. Proven on a real Mac 2026-11-17: CGPreflightScreenCaptureAccess()
returned False and every captured pixel was the identical colour. These tests
pin the detection and the explain-instead-of-grey behaviour, and that both are
no-ops off macOS so Windows and Linux are unchanged.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import capture, macos_permissions  # noqa: E402


class _FakeLib:
    """Stands in for a ctypes CDLL: named C functions returning a fixed value,
    with assignable restype/argtypes like the real thing."""

    def __init__(self, returns: dict):
        self._returns = returns

    def __getattr__(self, name):
        if name in self._returns:
            fn = lambda *a: self._returns[name]  # noqa: E731
            fn.restype = None
            fn.argtypes = []
            return fn
        raise AttributeError(name)


def _force_macos(monkeypatch, *, screen: bool, access: bool):
    monkeypatch.setattr(macos_permissions, "IS_MACOS", True)
    monkeypatch.setattr(
        macos_permissions, "_coregraphics",
        lambda: _FakeLib({
            "CGPreflightScreenCaptureAccess": screen,
            "CGRequestScreenCaptureAccess": screen,
        }),
    )
    monkeypatch.setattr(
        macos_permissions, "_application_services",
        lambda: _FakeLib({"AXIsProcessTrusted": access}),
    )


# --- detection ------------------------------------------------------------

def test_off_macos_everything_is_granted_without_touching_the_os(monkeypatch):
    monkeypatch.setattr(macos_permissions, "IS_MACOS", False)
    # If these called into the OS they would raise here; they must not.
    monkeypatch.setattr(macos_permissions, "_coregraphics", lambda: (_ for _ in ()).throw(AssertionError("called OS off macOS")))
    monkeypatch.setattr(macos_permissions, "_application_services", lambda: (_ for _ in ()).throw(AssertionError("called OS off macOS")))
    assert macos_permissions.screen_recording_granted() is True
    assert macos_permissions.accessibility_granted() is True


def test_screen_recording_missing_is_detected(monkeypatch):
    _force_macos(monkeypatch, screen=False, access=True)
    assert macos_permissions.screen_recording_granted() is False
    assert macos_permissions.accessibility_granted() is True


def test_screen_recording_present_is_detected(monkeypatch):
    _force_macos(monkeypatch, screen=True, access=True)
    assert macos_permissions.screen_recording_granted() is True


def test_accessibility_missing_is_detected(monkeypatch):
    _force_macos(monkeypatch, screen=True, access=False)
    assert macos_permissions.accessibility_granted() is False


def test_a_broken_check_never_blocks_capture(monkeypatch):
    # If the OS call throws, we must fail OPEN (report granted), never wedge the
    # picture behind a false "no permission".
    monkeypatch.setattr(macos_permissions, "IS_MACOS", True)
    monkeypatch.setattr(macos_permissions, "_coregraphics", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert macos_permissions.screen_recording_granted() is True


# --- the explain-instead-of-grey frame ------------------------------------

def test_permission_frame_is_not_a_flat_fill():
    img = macos_permissions.render_permission_frame((640, 480), ["Heading", "Body line"])
    assert img.size == (640, 480)
    colours = img.getcolors(maxcolors=100000)
    # The redacted capture is ONE colour; this frame must be many (border+text).
    assert colours is not None and len(colours) > 3


# --- capture integration: the real grab() path ----------------------------

def _capture_on_fake_macos(monkeypatch, granted: bool):
    monkeypatch.setattr(capture.macos_permissions, "IS_MACOS", True)
    monkeypatch.setattr(capture.macos_permissions, "screen_recording_granted", lambda: granted)
    cap = capture.ScreenCapture(synthetic=True)
    # Pretend a real (non-synthetic) capture is open on one 800x600 monitor.
    cap.synthetic = False
    cap._monitors = [{"index": 0, "label": "Primary", "width": 800, "height": 600, "left": 0, "top": 0}]
    cap._macos_sr_checked_at = 0.0
    return cap


def test_grab_shows_permission_frame_when_missing(monkeypatch):
    cap = _capture_on_fake_macos(monkeypatch, granted=False)
    frame = cap.grab()
    assert frame.size == (800, 600)
    colours = frame.getcolors(maxcolors=100000)
    assert colours is not None and len(colours) > 3  # the explanatory frame


def test_grab_returns_real_picture_once_granted(monkeypatch):
    cap = _capture_on_fake_macos(monkeypatch, granted=True)
    # No native/mss/wayland backend set, so grab() falls through to the
    # generated image - the point is it is NOT the permission frame.
    frame = cap.grab()
    assert cap._macos_permission_frame() is None
    assert frame is not None


def test_capture_permission_check_is_inert_off_macos(monkeypatch):
    monkeypatch.setattr(capture.macos_permissions, "IS_MACOS", False)
    cap = capture.ScreenCapture(synthetic=True)
    cap.synthetic = False
    cap._monitors = [{"index": 0, "width": 800, "height": 600, "left": 0, "top": 0}]
    assert cap._macos_permission_frame() is None
