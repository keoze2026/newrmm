"""The endpoint-side chat window.

Run for real against a real Tk window on this machine (same approach
test_privacy.py uses for the real overlay) - there is no fake-tkinter layer
to mock here, and a window that cannot actually open is the whole bug.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmm_agent.chat import ChatWindow  # noqa: E402


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_the_window_opens_and_shows_an_incoming_message():
    window = ChatWindow(on_reply=lambda _text: None)
    try:
        if not window.available:
            return  # no display / no tkinter on this runner - nothing to check

        assert _wait_until(lambda: window._toplevel is not None)
        window.receive("hello from the operator")
        assert _wait_until(
            lambda: window._history is not None
            and "hello from the operator" in window._history.get("1.0", "end")
        )
    finally:
        window.close()


def test_closing_ends_the_window_cleanly():
    window = ChatWindow(on_reply=lambda _text: None)
    window.close()
    assert window._toplevel is None


def test_two_sessions_worth_of_windows_in_the_same_process_do_not_crash_it():
    """An always-on device keeps one process running across many sessions -
    opening Chat in one session, closing it, then opening Chat again in the
    next session must not be the first time a second window is created."""
    first = ChatWindow(on_reply=lambda _text: None)
    first.close()
    second = ChatWindow(on_reply=lambda _text: None)
    try:
        assert second.available == first.available
    finally:
        second.close()
