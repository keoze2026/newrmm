"""Starting again after a restart: remembered, forgotten, and never by accident."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import autostart  # noqa: E402


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "session_file", lambda: tmp_path / "session.json")


class Recorder:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.ok


def test_a_session_is_remembered_and_the_service_turned_on():
    systemctl = Recorder()
    assert autostart.remember("wss://relay/api", "ABCD1234", enable=systemctl) is True
    assert autostart.saved() == ("wss://relay/api", "ABCD1234")
    assert systemctl.calls == [("enable", "rmm-agent-resume.service")]


def test_forgetting_clears_the_session_and_turns_the_service_off():
    autostart.remember("wss://relay/api", "ABCD1234", enable=Recorder())
    systemctl = Recorder()
    autostart.forget(disable=systemctl)
    assert autostart.saved() is None
    assert systemctl.calls == [("disable", "rmm-agent-resume.service")]


def test_another_sessions_ending_does_not_switch_off_this_one():
    autostart.remember("wss://relay/api", "ABCD1234", enable=Recorder())
    systemctl = Recorder()
    autostart.forget("SOMEOTHER", disable=systemctl)
    assert autostart.saved() == ("wss://relay/api", "ABCD1234")
    assert systemctl.calls == []


def test_forgetting_when_nothing_is_remembered_is_harmless():
    systemctl = Recorder()
    autostart.forget(disable=systemctl)
    assert systemctl.calls == []


def test_without_systemd_the_session_is_still_remembered_and_nothing_breaks(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda _name: None)
    assert autostart.remember("wss://relay/api", "ABCD1234") is False
    assert autostart.saved() == ("wss://relay/api", "ABCD1234")


def test_resume_with_nothing_remembered_does_nothing(monkeypatch):
    from rmm_agent import __main__ as agent

    def must_not_join(_args):
        raise AssertionError("joined a session that was never remembered")

    monkeypatch.setattr(agent, "cmd_join", must_not_join)
    assert agent.cmd_resume(None) == 0


def test_resume_rejoins_the_remembered_session(monkeypatch):
    from rmm_agent import __main__ as agent

    autostart.remember("wss://relay/api", "ABCD1234", enable=Recorder())
    joined = {}
    monkeypatch.setattr(agent, "cmd_join", lambda args: joined.update(relay=args.relay, code=args.code) or 0)
    assert agent.cmd_resume(None) == 0
    assert joined == {"relay": "wss://relay/api", "code": "ABCD1234"}


def test_stopping_on_purpose_turns_the_restart_off(monkeypatch):
    from rmm_agent import __main__ as agent

    autostart.remember("wss://relay/api", "ABCD1234", enable=Recorder())
    systemctl = Recorder()
    real_forget = autostart.forget
    monkeypatch.setattr(agent.autostart, "forget", lambda code=None: real_forget(code, disable=systemctl))
    monkeypatch.setattr(agent.background, "stop", lambda: False)
    agent.cmd_stop(None)
    assert autostart.saved() is None
    assert systemctl.calls == [("disable", "rmm-agent-resume.service")]


# ------------------------------------------------ every platform, not only Linux

import types  # noqa: E402

from rmm_agent import background, environment  # noqa: E402


def test_systemctl_gets_the_system_environment_not_the_bundles(monkeypatch):
    """A packaged agent's library path made `systemctl` fail with
    "libcrypto.so.3: version OPENSSL_3.4.0 not found", so auto-start was never
    turned on."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/x86_64-linux-gnu")
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setattr(autostart.shutil, "which", lambda _n: "/usr/bin/systemctl")
    seen = {}

    def fake_run(command, **options):
        seen.update(options)
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    assert autostart._systemctl("enable", autostart.UNIT) is True
    assert seen["env"]["LD_LIBRARY_PATH"] == "/usr/lib/x86_64-linux-gnu"


def test_the_library_path_is_dropped_when_there_was_no_original():
    env = environment.system_environment({"LD_LIBRARY_PATH": "/tmp/_MEI9", "HOME": "/h"})
    assert "LD_LIBRARY_PATH" not in env and env["HOME"] == "/h"


def test_the_library_path_is_restored_on_macos_too():
    env = environment.system_environment(
        {"DYLD_LIBRARY_PATH": "/bundle", "DYLD_LIBRARY_PATH_ORIG": "/usr/local/lib"}
    )
    assert env["DYLD_LIBRARY_PATH"] == "/usr/local/lib"


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, missing=False):
        self.values = {}
        self.deleted = []
        self.missing = missing

    def CreateKeyEx(self, root, path, _reserved, _access):
        self.opened = (root, path)
        return self

    def OpenKey(self, root, path, _reserved, _access):
        if self.missing:
            raise FileNotFoundError
        self.opened = (root, path)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def SetValueEx(self, _key, name, _reserved, _kind, value):
        self.values[name] = value

    def DeleteValue(self, _key, name):
        self.deleted.append(name)


def test_windows_starts_the_agent_at_login_with_a_run_entry(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(
        background, "own_command",
        lambda args: [r"C:\Users\U\AppData\Local\Programs\RMM Agent\rmm-agent.exe", *args],
    )
    assert autostart._windows_enable() is True
    assert fake.opened == ("HKCU", autostart.RUN_KEY)
    assert fake.values["RMMAgentResume"] == (
        r'"C:\Users\U\AppData\Local\Programs\RMM Agent\rmm-agent.exe" resume'
    )


def test_windows_removes_the_run_entry_and_a_missing_one_is_fine(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert autostart._windows_disable() is True
    assert fake.deleted == ["RMMAgentResume"]
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg(missing=True))
    assert autostart._windows_disable() is True


def test_macos_starts_the_agent_at_login_with_a_launch_agent(monkeypatch, tmp_path):
    import plistlib

    monkeypatch.setattr(autostart.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(background, "own_command", lambda args: ["/Applications/RMM Agent", *args])
    assert autostart._mac_enable() is True
    plist = plistlib.loads((tmp_path / "Library/LaunchAgents/com.rmm.agent.resume.plist").read_bytes())
    assert plist["ProgramArguments"] == ["/Applications/RMM Agent", "resume"]
    assert plist["RunAtLoad"] is True
    assert autostart._mac_disable() is True
    assert not (tmp_path / "Library/LaunchAgents/com.rmm.agent.resume.plist").exists()


def test_each_platform_uses_its_own_mechanism(monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, "_windows_enable", lambda: calls.append("windows") or True)
    monkeypatch.setattr(autostart, "_mac_enable", lambda: calls.append("macos") or True)
    monkeypatch.setattr(autostart, "_systemctl", lambda *a: calls.append("linux") or True)
    for name in ("win32", "darwin", "linux"):
        monkeypatch.setattr(autostart.sys, "platform", name)
        autostart.remember("wss://relay/api", "ABCD1234")
    assert calls == ["windows", "macos", "linux"]
