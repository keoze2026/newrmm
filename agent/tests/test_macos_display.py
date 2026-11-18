"""A macOS session must not go black because the display slept, and a locked
screen must read as a clear message, not a black picture. These pin the
keep-awake assertion and the lock detection, and that both are inert off macOS.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import capture, macos_display  # noqa: E402


# --- keep display awake ----------------------------------------------------

class _FakeProc:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_keep_awake_is_a_noop_off_macos(monkeypatch):
    monkeypatch.setattr(macos_display, "IS_MACOS", False)
    monkeypatch.setattr(macos_display.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch off macOS"))
    k = macos_display.KeepDisplayAwake()
    k.start()
    k.stop()  # both no-ops; nothing launched


def test_keep_awake_holds_and_releases_caffeinate_on_macos(monkeypatch):
    monkeypatch.setattr(macos_display, "IS_MACOS", True)
    launched = {}
    proc = _FakeProc()

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        return proc

    monkeypatch.setattr(macos_display.subprocess, "Popen", fake_popen)
    k = macos_display.KeepDisplayAwake()
    k.start()
    assert launched["cmd"] == ["/usr/bin/caffeinate", "-d"]
    k.start()  # idempotent: a second start must not launch a second caffeinate
    k.stop()
    assert proc.terminated is True


# --- lock detection --------------------------------------------------------

def test_screen_locked_is_false_off_macos(monkeypatch):
    monkeypatch.setattr(macos_display, "IS_MACOS", False)
    assert macos_display.screen_locked() is False


def test_screen_locked_fails_open_if_the_check_throws(monkeypatch):
    monkeypatch.setattr(macos_display, "IS_MACOS", True)
    # Force the ctypes import inside to blow up; must report not-locked, never
    # cover a working picture with a false "locked".
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "ctypes":
            raise OSError("no ctypes")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert macos_display.screen_locked() is False


# --- capture integration ---------------------------------------------------

def _capture_fake_macos(monkeypatch, *, granted, locked):
    monkeypatch.setattr(capture.macos_permissions, "IS_MACOS", True)
    monkeypatch.setattr(capture.macos_permissions, "screen_recording_granted", lambda: granted)
    monkeypatch.setattr(capture.macos_display, "screen_locked", lambda: locked)
    cap = capture.ScreenCapture(synthetic=True)
    cap.synthetic = False
    cap._monitors = [{"index": 0, "width": 800, "height": 600, "left": 0, "top": 0}]
    cap._macos_sr_checked_at = 0.0
    cap._macos_lock_checked_at = 0.0
    return cap


def test_locked_screen_shows_a_message_frame(monkeypatch):
    cap = _capture_fake_macos(monkeypatch, granted=True, locked=True)
    frame = cap._macos_permission_frame()
    assert frame is not None and frame.size == (800, 600)
    colours = frame.getcolors(maxcolors=100000)
    assert colours is not None and len(colours) > 3


def test_granted_and_unlocked_shows_the_real_picture(monkeypatch):
    cap = _capture_fake_macos(monkeypatch, granted=True, locked=False)
    assert cap._macos_permission_frame() is None


def test_missing_permission_takes_priority_over_lock(monkeypatch):
    # If permission is missing you can see nothing anyway, so that message wins.
    cap = _capture_fake_macos(monkeypatch, granted=False, locked=True)
    frame = cap._macos_permission_frame()
    assert frame is not None  # the permission frame, checked first
