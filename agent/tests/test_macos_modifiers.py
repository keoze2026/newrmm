"""A modifier whose release is lost (a drop mid-shortcut) stays stuck in macOS's
CGEvent flags, and release_all() cannot clear it because nothing tracked it - so
the next thing typed combines with it (a stuck Cmd makes letters into shortcuts:
"stray tabs"). The agent force-releases the modifiers on macOS at injector start
and at session end. These pin that, and that it is macOS-only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import remote_input  # noqa: E402
from rmm_agent.remote_input import InputInjector  # noqa: E402


class FakeKeyboard:
    def __init__(self):
        self.released = []

    def press(self, key):
        pass

    def release(self, key):
        self.released.append(key)


class FakeKey:
    shift = "shift"; shift_r = "shift_r"
    ctrl = "ctrl"; ctrl_r = "ctrl_r"
    alt = "alt"; alt_r = "alt_r"; alt_gr = "alt_gr"
    cmd = "cmd"; cmd_r = "cmd_r"
    caps_lock = "caps_lock"


def _injector():
    inj = InputInjector(enabled=False)
    inj.available = True
    inj._keyboard = FakeKeyboard()
    inj._Key = FakeKey
    inj._mouse = None
    return inj


MODS = {"shift", "shift_r", "ctrl", "ctrl_r", "alt", "alt_r", "alt_gr", "cmd", "cmd_r", "caps_lock"}


def test_clear_releases_every_modifier_on_macos(monkeypatch):
    monkeypatch.setattr(remote_input, "_MACOS", True)
    inj = _injector()
    inj._clear_macos_modifiers()
    assert set(inj._keyboard.released) == MODS


def test_clear_is_a_noop_off_macos(monkeypatch):
    monkeypatch.setattr(remote_input, "_MACOS", False)
    inj = _injector()
    inj._clear_macos_modifiers()
    assert inj._keyboard.released == []


def test_release_all_sweeps_modifiers_on_macos(monkeypatch):
    monkeypatch.setattr(remote_input, "_MACOS", True)
    inj = _injector()
    inj.release_all()
    assert MODS.issubset(set(inj._keyboard.released))


def test_release_all_off_macos_only_releases_tracked_keys(monkeypatch):
    monkeypatch.setattr(remote_input, "_MACOS", False)
    inj = _injector()
    inj._pressed_keys = {"a"}
    inj.release_all()
    # Only the tracked key, never the macOS modifier sweep.
    assert inj._keyboard.released == ["a"]
