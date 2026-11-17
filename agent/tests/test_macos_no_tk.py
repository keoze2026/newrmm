"""macOS must never create a Tk window. Tk on macOS has to own the main thread,
which the tray already holds, so any Tk root built on a worker thread aborts the
whole process (the NSApplication/Tcl crash seen in CI). consent, the clipboard
and error dialogs already avoid Tk; these tests pin that the chat and the
privacy blank do too, and that both degrade cleanly instead of crashing.
Windows/Linux keep their Tk paths - asserted by the off-macOS cases.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import chat, privacy  # noqa: E402


# --- chat -----------------------------------------------------------------

def test_chat_on_macos_never_starts_the_tk_gui_thread(monkeypatch):
    monkeypatch.setattr(chat, "IS_MACOS", True)

    def boom():
        raise AssertionError("the Tk GUI thread must not start on macOS")

    monkeypatch.setattr(chat, "_ensure_gui_thread", boom)
    win = chat.ChatWindow(on_reply=lambda _t: None)
    assert win.available is True  # still delivers messages
    win.close()  # must not hang or touch Tk


def test_chat_on_macos_delivers_messages_as_a_notification(monkeypatch):
    monkeypatch.setattr(chat, "IS_MACOS", True)
    monkeypatch.setattr(chat, "_ensure_gui_thread", lambda: None)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(chat.subprocess, "run", fake_run)
    win = chat.ChatWindow(on_reply=lambda _t: None)
    win.receive("hello from the operator")
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    joined = " ".join(calls[0])
    assert "display notification" in joined and "hello from the operator" in joined


def test_osascript_quoting_escapes_quotes_and_backslashes():
    assert chat._osa_quote('a"b\\c') == '"a\\"b\\\\c"'


def test_chat_off_macos_still_uses_the_tk_path(monkeypatch):
    monkeypatch.setattr(chat, "IS_MACOS", False)
    started = {"n": 0}
    monkeypatch.setattr(chat, "_ensure_gui_thread", lambda: started.__setitem__("n", started["n"] + 1))
    # Pretend the GUI decided it is unavailable so __init__ returns promptly.
    chat._gui_decided.set()
    chat._gui_unavailable.set()
    try:
        chat.ChatWindow(on_reply=lambda _t: None)
        assert started["n"] == 1  # the Tk path was taken off macOS
    finally:
        chat._gui_decided.clear()
        chat._gui_unavailable.clear()


# --- privacy blank --------------------------------------------------------

def test_privacy_mode_is_unavailable_on_macos(monkeypatch):
    monkeypatch.setattr(privacy, "MACOS", True)
    monkeypatch.setattr(privacy, "WINDOWS", False)
    assert privacy.supported_mode() == privacy.MODE_UNAVAILABLE


def test_privacy_enable_on_macos_does_not_spawn_tk(monkeypatch):
    monkeypatch.setattr(privacy, "MACOS", True)
    monkeypatch.setattr(privacy, "WINDOWS", False)
    # If the overlay thread were started it would import tkinter; make that fail
    # loudly so a regression is caught here, not only on a real Mac.
    monkeypatch.setitem(sys.modules, "tkinter", None)
    pb = privacy.PrivacyBlank()
    result = pb.enable()
    assert result["active"] is False
    assert result["mode"] == privacy.MODE_UNAVAILABLE
    assert pb._thread is None
    assert pb.active is False


def test_privacy_still_works_off_macos(monkeypatch):
    # Linux overlay path is still selectable (guest-lock when nothing dims).
    monkeypatch.setattr(privacy, "MACOS", False)
    monkeypatch.setattr(privacy, "WINDOWS", False)
    monkeypatch.setattr(privacy.dimmer, "available", lambda: False)
    assert privacy.supported_mode() == privacy.MODE_GUEST_LOCK
