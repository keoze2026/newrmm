"""Telling a double-click from a terminal on Windows.

A packaged one-file agent is two processes sharing the console: a small
launcher and the program it unpacks. Counting processes on the console as if
there were one meant a double-click or the installer was mistaken for a
terminal, the black console window was never hidden, and closing it ended the
agent ("the console window was closed").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rmm_agent import background  # noqa: E402


def test_a_packaged_agent_alone_on_its_console_is_a_double_click():
    assert background.sole_console_owner(2, own=2) is True
    assert background.shares_console(2, own=2) is False


def test_a_packaged_agent_with_a_shell_beside_it_is_a_terminal():
    assert background.sole_console_owner(3, own=2) is False
    assert background.shares_console(3, own=2) is True


def test_an_unpackaged_agent_counts_itself_as_one():
    assert background.sole_console_owner(1, own=1) is True
    assert background.shares_console(2, own=1) is True


def test_no_console_information_is_never_treated_as_either():
    assert background.sole_console_owner(None, own=2) is False
    assert background.shares_console(None, own=2) is False


def test_a_packaged_build_knows_it_is_two_processes(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert background.own_processes() == 2
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert background.own_processes() == 1


def test_the_background_copy_is_told_to_let_go_of_any_console(monkeypatch):
    seen = {}

    class FakeProcess:
        pid = 1

    monkeypatch.setattr(background.subprocess, "Popen", lambda cmd, **o: seen.update(o) or FakeProcess())
    background.spawn_detached(["join"])
    assert seen["env"]["RMM_BACKGROUND"] == "1"
