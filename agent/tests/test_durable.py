"""The saved session was found at 0 bytes after a restart straight after it was
written, so the restart service had nothing to rejoin and exited silently."""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from rmm_agent import autostart, durable  # noqa: E402


def test_a_durable_write_is_forced_to_disk_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(durable.os, "fsync", lambda fd: synced.append(fd) or real_fsync(fd))
    target = tmp_path / "session.json"
    durable.write_text(target, '{"code": "ABCD1234"}')
    assert target.read_text() == '{"code": "ABCD1234"}'
    assert not (tmp_path / "session.json.tmp").exists()
    assert len(synced) >= 1  # the file itself; the folder too on POSIX
    if sys.platform != "win32":
        assert len(synced) >= 2


def test_replacing_a_file_never_leaves_it_empty_in_between(tmp_path, monkeypatch):
    target = tmp_path / "relay.txt"
    target.write_text("old")
    seen = []
    real_replace = durable.os.replace

    def spy(source, destination):
        seen.append(Path(source).read_text())  # the new contents are complete before the swap
        real_replace(source, destination)

    monkeypatch.setattr(durable.os, "replace", spy)
    durable.write_text(target, "new")
    assert seen == ["new"] and target.read_text() == "new"


@pytest.fixture
def private_state(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "session_file", lambda: tmp_path / "session.json")
    return tmp_path


def test_an_empty_saved_session_is_reported_not_silently_ignored(private_state, caplog):
    (private_state / "session.json").write_text("")
    caplog.set_level(logging.WARNING, logger="rmm_agent.autostart")
    assert autostart.saved() is None
    assert any("empty or damaged" in r.getMessage() for r in caplog.records)


def test_a_missing_saved_session_is_just_none(private_state, caplog):
    caplog.set_level(logging.WARNING, logger="rmm_agent.autostart")
    assert autostart.saved() is None
    assert not caplog.records


def test_resume_says_so_when_there_is_nothing_to_rejoin(private_state, caplog):
    from rmm_agent import __main__ as agent

    caplog.set_level(logging.INFO, logger="rmm_agent")
    assert agent.cmd_resume(None) == 0
    assert any("nothing to resume" in r.getMessage() for r in caplog.records)
