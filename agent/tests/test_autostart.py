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
