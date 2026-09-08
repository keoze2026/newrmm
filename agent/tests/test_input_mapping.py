"""Operator coordinates must land on the right pixel on every platform.

These cases are the ones this Linux machine cannot reproduce in hardware: a
Retina display where the captured frame is twice the logical size, a Windows
display at 150% scaling, and a second monitor with a non-zero origin.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent.capture import ScreenCapture  # noqa: E402
from rmm_agent.remote_input import InputInjector  # noqa: E402


class FakeMouse:
    def __init__(self):
        self.position = (0, 0)
        self.pressed = []

    def press(self, button):
        self.pressed.append(("press", button))

    def release(self, button):
        self.pressed.append(("release", button))

    def scroll(self, dx, dy):
        self.pressed.append(("scroll", dx, dy))


class FakeButton:
    left = "left"
    right = "right"
    middle = "middle"


@pytest.fixture
def injector():
    inj = InputInjector(enabled=False)
    inj.available = True
    inj._mouse = FakeMouse()
    inj._Button = FakeButton
    inj._keyboard = None
    return inj


def move(injector, x, y, geometry):
    injector.apply({"kind": "mouse", "action": "move", "x": x, "y": y}, geometry)
    return injector._mouse.position


def test_centre_of_a_single_display(injector):
    assert move(injector, 0.5, 0.5, (0, 0, 1920, 1200)) == (960, 600)


def test_corners_of_a_single_display(injector):
    assert move(injector, 0.0, 0.0, (0, 0, 1920, 1200)) == (0, 0)
    assert move(injector, 1.0, 1.0, (0, 0, 1920, 1200)) == (1920, 1200)


def test_retina_display_maps_to_logical_points_not_captured_pixels(injector):
    """A 2560x1600 Retina panel reports 1280x800 logical points and is captured
    at 2560x1600. Input must use the logical size, or every click lands at
    double the intended offset."""
    logical = (0, 0, 1280, 800)
    assert move(injector, 0.5, 0.5, logical) == (640, 400)
    assert move(injector, 1.0, 1.0, logical) == (1280, 800)


def test_windows_scaled_display(injector):
    """At 150% scaling a 2880x1800 panel is 1920x1200 logical. With the process
    marked DPI-aware both capture and input use physical pixels, so the mapping
    is the plain one."""
    assert move(injector, 0.25, 0.75, (0, 0, 2880, 1800)) == (720, 1350)


def test_second_monitor_origin_is_added(injector):
    """A monitor to the right of the primary starts at x=1920, so a click in
    its centre is at 1920 + 960."""
    assert move(injector, 0.5, 0.5, (1920, 0, 1920, 1080)) == (2880, 540)


def test_monitor_above_the_primary_has_a_negative_origin(injector):
    assert move(injector, 0.5, 0.5, (0, -1080, 1920, 1080)) == (960, -540)


def test_buttons_are_pressed_and_released(injector):
    geometry = (0, 0, 1920, 1200)
    injector.apply({"kind": "mouse", "action": "down", "button": "right",
                    "x": 0.5, "y": 0.5}, geometry)
    injector.apply({"kind": "mouse", "action": "up", "button": "right",
                    "x": 0.5, "y": 0.5}, geometry)
    assert injector._mouse.pressed == [("press", "right"), ("release", "right")]


def test_an_unknown_button_falls_back_to_left(injector):
    injector.apply({"kind": "mouse", "action": "down", "button": "thumb",
                    "x": 0.1, "y": 0.1}, (0, 0, 100, 100))
    assert injector._mouse.pressed == [("press", "left")]


def test_a_zero_sized_display_does_not_move_the_pointer(injector):
    injector._mouse.position = (5, 5)
    injector.apply({"kind": "mouse", "action": "move", "x": 0.5, "y": 0.5},
                   (0, 0, 0, 0))
    assert injector._mouse.position == (5, 5)


def test_capture_geometry_follows_the_selected_monitor():
    capture = ScreenCapture(synthetic=True)
    capture._monitors = [
        {"index": 0, "label": "Monitor 1", "width": 1920, "height": 1200, "left": 0, "top": 0},
        {"index": 1, "label": "Monitor 2", "width": 2560, "height": 1440, "left": 1920, "top": -240},
    ]
    assert capture.geometry == (0, 0, 1920, 1200)
    assert capture.select(1) is True
    assert capture.geometry == (1920, -240, 2560, 1440)
    assert capture.select(7) is False
    assert capture.geometry == (1920, -240, 2560, 1440)


def test_synthetic_capture_still_reports_a_usable_geometry():
    capture = ScreenCapture(synthetic=True)
    left, top, width, height = capture.geometry
    assert (left, top) == (0, 0)
    assert width > 0 and height > 0
