"""macOS must never use Tk: it crashed the built agent in CI with
"-[NSApplication macOSVersion]: unrecognized selector". The consent prompt,
the code window, error messages and the clipboard all go through system tools.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import clipboard, consent, launcher, macos_dialogs  # noqa: E402


def result(stdout="", stderr="", returncode=0):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def fake_osascript(monkeypatch, outcome):
    seen = {}

    def run(command, **options):
        seen["script"] = command[2]
        seen["options"] = options
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(macos_dialogs.subprocess, "run", run)
    return seen


def test_allow_is_the_only_answer_that_grants_consent(monkeypatch):
    fake_osascript(monkeypatch, result("button returned:Allow, gave up:false\n"))
    assert macos_dialogs.consent("May we?") is True


def test_deny_a_closed_dialog_and_no_answer_are_all_refusals(monkeypatch):
    fake_osascript(monkeypatch, result("button returned:Deny, gave up:false\n"))
    assert macos_dialogs.consent("May we?") is False
    fake_osascript(monkeypatch, result("button returned:Allow, gave up:true\n"))
    assert macos_dialogs.consent("May we?") is False
    fake_osascript(monkeypatch, result(returncode=1, stderr="execution error: User canceled. (-128)"))
    assert macos_dialogs.consent("May we?") is False


def test_no_dialog_at_all_is_reported_so_the_caller_can_fall_back(monkeypatch):
    fake_osascript(monkeypatch, FileNotFoundError("osascript"))
    assert macos_dialogs.consent("May we?") is None
    fake_osascript(monkeypatch, result(returncode=1, stderr="not allowed to send keystrokes (-1743)"))
    assert macos_dialogs.consent("May we?") is None


def test_quotes_in_a_message_cannot_break_out_of_the_script(monkeypatch):
    seen = fake_osascript(monkeypatch, result("button returned:Deny, gave up:false\n"))
    macos_dialogs.consent('say "hi" \\ now')
    assert 'say \\"hi\\" \\\\ now' in seen["script"]


def test_the_code_is_read_back_and_cancel_is_none(monkeypatch):
    fake_osascript(monkeypatch, result("button returned:Connect, text returned:ABCD1234\n"))
    assert macos_dialogs.ask_code("") == "ABCD1234"
    fake_osascript(monkeypatch, result(returncode=1, stderr="User canceled. (-128)"))
    assert macos_dialogs.ask_code("") is None
    fake_osascript(monkeypatch, result(returncode=1, stderr="no window server"))
    with pytest.raises(RuntimeError):
        macos_dialogs.ask_code("")


def test_the_consent_prompt_on_macos_never_touches_tk(monkeypatch):
    monkeypatch.setattr(consent.sys, "platform", "darwin")
    monkeypatch.setattr(macos_dialogs, "consent", lambda message, timeout=120.0: True)
    monkeypatch.setitem(sys.modules, "tkinter", None)  # importing it would now fail
    assert consent._ask_with_tk("ABCD1234", None, 120.0) is True


def test_the_code_window_on_macos_checks_the_code_and_never_touches_tk(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "tkinter", None)
    answers = iter(["wrong", "abcd1234"])
    monkeypatch.setattr(macos_dialogs, "ask_code", lambda prefill="", notice="": next(answers))
    monkeypatch.setattr(launcher, "check_code", lambda relay, code: (code == "ABCD1234", "Not valid"))
    assert launcher._ask_with_window("wss://relay/api") == ("ABCD1234", "wss://relay/api")


def test_the_clipboard_on_macos_uses_pbcopy_and_pbpaste_and_never_tk(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def run(command, **options):
        calls.append((command[0], options.get("input")))
        return types.SimpleNamespace(stdout="from the clipboard".encode(), returncode=0)

    monkeypatch.setattr(clipboard.subprocess, "run", run)
    assert clipboard.available() is True
    assert clipboard.get_text() == "from the clipboard"
    assert clipboard.set_text("héllo") is True
    assert calls == [("pbpaste", None), ("pbcopy", "héllo".encode("utf-8"))]
