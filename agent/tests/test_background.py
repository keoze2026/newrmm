"""The agent keeps running when the terminal that started it goes away."""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import background  # noqa: E402


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    """Never touch the real pid file: a real agent may be running."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield


def test_started_from_a_terminal_only_when_there_is_one(monkeypatch):
    class Tty:
        def isatty(self):
            return True

    class NoTty:
        def isatty(self):
            return False

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(background, "WINDOWS", False)
    monkeypatch.setattr(sys, "stdin", Tty())
    assert background.launched_from_terminal() is True
    monkeypatch.setattr(sys, "stdin", NoTty())
    assert background.launched_from_terminal() is False
    monkeypatch.setattr(sys, "stdin", None)
    assert background.launched_from_terminal() is False


def test_the_agent_can_run_itself_again():
    command = background.own_command(["join", "--code", "ABCD1234"])
    assert command[0] == sys.executable
    assert command[-3:] == ["join", "--code", "ABCD1234"]
    assert "rmm_agent" in command


def test_the_pid_file_records_and_clears_this_process():
    assert background.running_pid() is None
    background.write_pid()
    assert background.running_pid() == os.getpid()
    background.clear_pid()
    assert background.running_pid() is None


def test_a_stale_pid_is_not_reported_as_running():
    background.pid_file().write_text("999999")
    assert background.running_pid() is None


def test_a_detached_agent_outlives_its_parent_and_can_be_stopped():
    """The real thing: start one detached, check it is out of this terminal's
    process group, and stop it. It cannot reach a relay, so it sits retrying
    and never shows a consent dialog."""
    pid = background.spawn_detached(
        ["join", "--relay", "ws://127.0.0.1:9", "--code", "TESTCODE", "--no-tray"]
    )
    try:
        assert os.getpgid(pid) != os.getpgid(0), (
            "the agent is still in this terminal's process group, so Ctrl+C "
            "or closing the terminal would still kill it"
        )

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and background.running_pid() != pid:
            time.sleep(0.25)
        assert background.running_pid() == pid, "the agent never recorded itself"

        assert background.stop() is True
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and background.running_pid() is not None:
            time.sleep(0.1)
        assert background.running_pid() is None
    finally:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def test_stopping_when_nothing_runs_is_harmless():
    assert background.stop() is False


def test_detached_child_starts_with_a_clean_packaging_environment(monkeypatch):
    """A one-file build's child must unpack its own files, not borrow ones
    that vanish when the starting process exits."""
    seen = {}

    class FakeProcess:
        pid = 1

    def fake_popen(command, **options):
        seen.update(options)
        return FakeProcess()

    monkeypatch.setattr(background.subprocess, "Popen", fake_popen)
    background.spawn_detached(["join"])
    assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
