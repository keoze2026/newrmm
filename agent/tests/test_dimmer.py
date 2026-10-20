"""Darkening the physical display while the operator keeps the real picture.

All against a fake display: a unit test must never darken the screen of whoever
is at the keyboard.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmm_agent import dimmer, privacy  # noqa: E402

VERBOSE = """Screen 0: minimum 320 x 200, current 1920 x 1200, maximum 16384 x 16384
eDP connected primary 1920x1200+0+0 (0x5c) normal (normal left inverted right x axis y axis) 302mm x 188mm
\tIdentifier: 0x5b
\tBrightness: 0.8
\tGamma:      1.0:1.0:1.0
HDMI-A-0 connected 2560x1440+1920+0 (0x61) normal (normal left inverted right x axis y axis) 600mm x 340mm
\tBrightness: 1.0
DisplayPort-0 disconnected (normal left inverted right x axis y axis)
\tBrightness: 0.5
"""


class FakeDisplay:
    def __init__(self):
        self.commands: list[list[str]] = []
        self.guards: list[str] = []
        self.guard_stopped = 0

    def run(self, command):
        self.commands.append(command)
        return VERBOSE if "--verbose" in command else ""

    def guard(self, script):
        self.guards.append(script)

        class Handle:
            def terminate(handle):  # noqa: N805
                self.guard_stopped += 1

        return Handle()

    def dimmer(self):
        return dimmer.Dimmer(run=self.run, spawn_guard=self.guard)

    def brightness_commands(self):
        return [c for c in self.commands if "--brightness" in c]


def test_only_connected_outputs_are_found_with_their_current_brightness():
    assert dimmer.parse_outputs(VERBOSE) == {"eDP": 0.8, "HDMI-A-0": 1.0}


def test_every_connected_output_goes_dark():
    fake = FakeDisplay()
    assert fake.dimmer().dim(guard_seconds=60) is True
    assert [c[2:] for c in fake.brightness_commands()] == [
        ["eDP", "--brightness", "0"],
        ["HDMI-A-0", "--brightness", "0"],
    ]


def test_the_safety_net_is_armed_before_anything_goes_dark():
    """If the agent died between darkening and arming the net, the screen would
    stay black for good."""
    fake = FakeDisplay()
    order = []
    original_run, original_guard = fake.run, fake.guard

    fake.run = lambda c: order.append("dim" if "--brightness" in c else "read") or original_run(c)
    fake.guard = lambda script: order.append("guard") or original_guard(script)
    dimmer.Dimmer(run=fake.run, spawn_guard=fake.guard).dim(guard_seconds=60)

    assert order.index("guard") < order.index("dim")


def test_the_safety_net_restores_the_original_brightness_not_a_guess():
    fake = FakeDisplay()
    fake.dimmer().dim(guard_seconds=60)
    script = fake.guards[0]
    assert script.startswith("sleep 60;")
    assert "--output eDP --brightness 0.8" in script
    assert "--output HDMI-A-0 --brightness 1.0" in script


def test_restoring_puts_each_output_back_as_it_was_and_stands_the_net_down():
    fake = FakeDisplay()
    d = fake.dimmer()
    d.dim(guard_seconds=60)
    fake.commands.clear()

    d.restore()

    assert [c[2:] for c in fake.brightness_commands()] == [
        ["eDP", "--brightness", "0.8"],
        ["HDMI-A-0", "--brightness", "1.0"],
    ]
    assert fake.guard_stopped == 1
    assert d.saved == {}


def test_nothing_connected_means_nothing_darkened():
    class Nothing(FakeDisplay):
        def run(self, command):
            self.commands.append(command)
            return "DisplayPort-0 disconnected\n"

    fake = Nothing()
    assert dimmer.Dimmer(run=fake.run, spawn_guard=fake.guard).dim(60) is False
    assert fake.brightness_commands() == []


def test_a_failed_darkening_is_reported_not_claimed():
    class Broken(FakeDisplay):
        def run(self, command):
            if "--brightness" in command:
                raise RuntimeError("xrandr failed")
            return super().run(command)

    fake = Broken()
    assert dimmer.Dimmer(run=fake.run, spawn_guard=fake.guard).dim(60) is False
    assert fake.guard_stopped == 1, "the net must be stood down when nothing was darkened"


# ------------------------------------------------------------- the way out
def test_escape_three_times_quickly_releases_it():
    released = []
    now = [0.0]
    press = dimmer.escape_counter("ESC", lambda: released.append(True), lambda: now[0])
    for t in (0.0, 0.4, 0.8):
        now[0] = t
        press("ESC")
    assert released == [True]


def test_escape_pressed_slowly_does_not():
    released = []
    now = [0.0]
    press = dimmer.escape_counter("ESC", lambda: released.append(True), lambda: now[0])
    for t in (0.0, 3.0, 6.0):
        now[0] = t
        press("ESC")
    assert released == []


def test_other_keys_never_count_and_never_stop_the_listener():
    released = []
    press = dimmer.escape_counter("ESC", lambda: released.append(True), lambda: 0.0)
    for key in ("a", "enter", None):
        assert press(key) is None
    assert released == []


# --------------------------------------------------- how the blank uses it
def test_a_blank_on_x11_darkens_the_display_and_reports_a_live_view():
    fake = FakeDisplay()
    blank = privacy.PrivacyBlank(watchdog_seconds=60)
    blank.mode = privacy.MODE_EXCLUDED
    blank._dimmer = fake.dimmer()
    blank._watch_escape = lambda: None

    state = blank.enable()
    try:
        assert state["active"] is True
        assert state["mode"] == privacy.MODE_EXCLUDED
        assert state["input_blocked"] is False, "local input must keep flowing"
        assert blank._thread is None, "no overlay window may be drawn: the capture would see it"
    finally:
        blank.disable()

    assert blank.active is False
    assert fake.brightness_commands()[-1][2:] == ["HDMI-A-0", "--brightness", "1.0"]


def test_if_the_display_cannot_be_darkened_it_falls_back_to_the_overlay():
    class Nothing(FakeDisplay):
        def run(self, command):
            return ""

    blank = privacy.PrivacyBlank(watchdog_seconds=60)
    blank.mode = privacy.MODE_EXCLUDED
    blank._dimmer = dimmer.Dimmer(run=Nothing().run, spawn_guard=Nothing().guard)

    # The overlay itself needs a display; only check the decision it makes.
    blank._run = lambda: blank._ready.put("stopped here on purpose")
    state = blank.enable()

    assert blank.mode == privacy.MODE_GUEST_LOCK
    assert blank._dimmer is None
    assert state["active"] is False
