"""The guest lock's callbacks must never stop their own listener.

This is a regression test for a bug that shipped. Every callback returned False,
which in pynput stops the listener, so the lock released itself on the first
mouse move or key press - and on Python 3.13, stopping a listener from inside its
own callback raises "'_thread._ThreadHandle' object is not callable". The earlier
input-block test only checked that the block turned on and off, never that it
survived an event, so it passed while the lock was broken.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmm_agent.privacy import suppressing_callbacks  # noqa: E402

ESC = object()


def make(escaped):
    return suppressing_callbacks(escape_key=ESC, on_escape=lambda: escaped.append(True))


def test_no_callback_returns_false():
    callbacks = make([])
    samples = {
        "on_press": [("a",), (ESC,), (None,)],
        "on_release": [("a",), (ESC,)],
        "on_click": [(10, 20, "left", True), (0, 0, "right", False)],
        "on_scroll": [(1, 2, 0, -1)],
    }
    for name, calls in samples.items():
        for args in calls:
            result = callbacks[name](*args)
            assert result is not False, f"{name}{args} returned False and would stop the listener"
            assert result is None


def test_escape_releases_the_lock():
    escaped: list[bool] = []
    make(escaped)["on_press"](ESC)
    assert escaped == [True]


def test_other_keys_do_not_release_the_lock():
    escaped: list[bool] = []
    callbacks = make(escaped)
    for key in ("a", "enter", None, object()):
        callbacks["on_press"](key)
    assert escaped == []
