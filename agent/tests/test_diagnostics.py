"""Evidence for an agent that dies without a word."""
import faulthandler
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rmm_agent import diagnostics  # noqa: E402


def test_install_enables_native_crash_stacks_into_the_state_directory(tmp_path):
    was_enabled = faulthandler.is_enabled()
    try:
        diagnostics.install(tmp_path)
        assert faulthandler.is_enabled()
        assert (tmp_path / "crash.log").exists()
    finally:
        if not was_enabled:
            faulthandler.disable()


def test_the_heartbeat_logs_until_it_is_stopped(caplog):
    caplog.set_level(logging.INFO, logger="rmm_agent.diagnostics")
    stop = diagnostics.heartbeat(interval=0.05)
    time.sleep(0.3)
    stop.set()
    beats = [r for r in caplog.records if r.getMessage() == "still running"]
    assert len(beats) >= 2
    seen = len(beats)
    time.sleep(0.2)
    assert len([r for r in caplog.records if r.getMessage() == "still running"]) <= seen + 1


def test_install_never_breaks_the_agent_when_the_directory_is_unusable(tmp_path):
    diagnostics.install(tmp_path / "does" / "not" / "exist")  # must not raise
