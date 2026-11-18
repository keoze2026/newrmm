"""App Translocation: run from Downloads unquarantined and macOS executes the
app from a random, read-only mount, so sys.executable is a throwaway path. A
LaunchAgent written from there points at nothing and auto-start silently never
works. These pin the detection and that auto-start refuses (rather than writes a
broken entry) when translocated. Saved settings are unaffected - they live under
~/Library/Application Support, an absolute home path - so only auto-start needs
guarding. macOS-only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import autostart, macos_app  # noqa: E402

TRANS = "/private/var/folders/aa/xx/T/AppTranslocation/ABC-123/d/rmm-agent.app/Contents/MacOS/rmm-agent"
REAL = "/Applications/rmm-agent.app/Contents/MacOS/rmm-agent"


def test_detects_translocation_on_macos(monkeypatch):
    monkeypatch.setattr(macos_app, "IS_MACOS", True)
    assert macos_app.is_translocated(TRANS) is True
    assert macos_app.is_translocated(REAL) is False


def test_translocation_is_never_flagged_off_macos(monkeypatch):
    monkeypatch.setattr(macos_app, "IS_MACOS", False)
    assert macos_app.is_translocated(TRANS) is False


def test_app_bundle_path_is_extracted():
    assert macos_app.app_bundle_path(REAL) == "/Applications/rmm-agent.app"
    assert macos_app.app_bundle_path("/usr/bin/python3") is None


def test_autostart_refuses_when_translocated(monkeypatch, tmp_path):
    monkeypatch.setattr(macos_app, "is_translocated", lambda: True)
    plist = tmp_path / "LaunchAgents" / "com.rmm.agent.resume.plist"
    monkeypatch.setattr(autostart, "_mac_plist", lambda: plist)
    assert autostart._mac_enable() is False
    assert not plist.exists()  # no broken auto-start written


def test_autostart_writes_the_plist_when_not_translocated(monkeypatch, tmp_path):
    monkeypatch.setattr(macos_app, "is_translocated", lambda: False)
    plist = tmp_path / "LaunchAgents" / "com.rmm.agent.resume.plist"
    monkeypatch.setattr(autostart, "_mac_plist", lambda: plist)
    monkeypatch.setattr(autostart, "_resume_command", lambda: ["/Applications/rmm-agent.app/Contents/MacOS/rmm-agent", "resume"])
    assert autostart._mac_enable() is True
    assert plist.exists()
    import plistlib
    data = plistlib.loads(plist.read_bytes())
    assert data["Label"] == "com.rmm.agent.resume"
    assert data["ProgramArguments"][-1] == "resume"
