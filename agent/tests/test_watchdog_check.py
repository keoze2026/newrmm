"""The silent watchdog helper: never shows a window, only acts when needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import watchdog_check  # noqa: E402


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield


def test_does_nothing_when_the_agent_is_already_running(monkeypatch):
    monkeypatch.setattr(watchdog_check.background, "running_pid", lambda: 12345)

    def must_not_launch(*_args, **_kwargs):
        raise AssertionError("launched the agent while it was already running")

    monkeypatch.setattr(watchdog_check.subprocess, "Popen", must_not_launch)
    assert watchdog_check.main() == 0


def test_launches_the_main_agent_detached_and_silent_when_it_is_not_running(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog_check.background, "running_pid", lambda: None)
    agent = tmp_path / watchdog_check.MAIN_AGENT_NAME
    agent.write_text("not a real exe, just needs to exist")
    monkeypatch.setattr(watchdog_check.sys, "executable", str(tmp_path / "rmm-agent-watchdog.exe"))

    seen = {}

    class FakeProcess:
        pid = 1

    def fake_popen(command, **options):
        seen["command"] = command
        seen["options"] = options
        return FakeProcess()

    monkeypatch.setattr(watchdog_check.subprocess, "Popen", fake_popen)
    assert watchdog_check.main() == 0
    assert seen["command"] == [str(agent), "resume"]
    assert seen["options"]["stdout"] == watchdog_check.subprocess.DEVNULL


def test_gives_up_quietly_if_the_main_agent_is_simply_not_there(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog_check.background, "running_pid", lambda: None)
    monkeypatch.setattr(watchdog_check.sys, "executable", str(tmp_path / "rmm-agent-watchdog.exe"))

    def must_not_launch(*_args, **_kwargs):
        raise AssertionError("tried to launch an agent that does not exist")

    monkeypatch.setattr(watchdog_check.subprocess, "Popen", must_not_launch)
    assert watchdog_check.main() == 1
