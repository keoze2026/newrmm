"""The privacy blank: overlay lifecycle, honesty about the mode, and safety.

These run against the real Tk overlay, so the screen goes black for a second or
two at a time. Local input is never blocked here - that path is verified
separately, in a subprocess with a hard watchdog, so a failing test cannot leave
the machine locked.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import privacy  # noqa: E402


def overlay_only(instance):
    """Force the overlay lock, whatever this machine could do.

    On X11 the real blank darkens the physical display, and a unit test must
    never do that to whoever is at the keyboard. These tests are about the
    overlay path, so they use it; the darkening path is tested against a fake
    display in test_dimmer.py.
    """
    instance._dimmer = None
    instance.mode = privacy.MODE_GUEST_LOCK
    return instance


@pytest.fixture
def blank():
    instance = overlay_only(privacy.PrivacyBlank())
    yield instance
    # Never leave a blank up, whatever the test did.
    instance.disable()


def test_this_platform_reports_a_mode():
    mode = privacy.supported_mode()
    assert mode in (privacy.MODE_EXCLUDED, privacy.MODE_GUEST_LOCK)


def test_linux_only_claims_a_live_view_when_it_can_darken_the_display():
    """The operator keeps the real picture only if the physical display can be
    darkened (X11 with xrandr). Anywhere else Linux falls back to the overlay
    lock, and must say so rather than claim a live view it cannot deliver."""
    if sys.platform.startswith("linux"):
        from rmm_agent import dimmer

        expected = privacy.MODE_EXCLUDED if dimmer.available() else privacy.MODE_GUEST_LOCK
        assert privacy.supported_mode() == expected


def test_starts_inactive(blank):
    state = blank.state()
    assert state["active"] is False
    assert state["input_blocked"] is False
    assert state["seconds"] == 0


def test_enable_then_disable(blank):
    state = blank.enable(block_input=False)
    assert state["active"] is True, state
    assert state["mode"] in (privacy.MODE_EXCLUDED, privacy.MODE_GUEST_LOCK)
    assert blank.active is True

    time.sleep(0.5)
    assert blank.state()["seconds"] > 0

    state = blank.disable()
    assert state["active"] is False
    assert blank.active is False


def test_enabling_twice_is_harmless(blank):
    first = blank.enable(block_input=False)
    second = blank.enable(block_input=False)
    assert first["active"] and second["active"]
    assert blank.disable()["active"] is False


def test_disabling_when_off_is_harmless(blank):
    assert blank.disable()["active"] is False


def test_the_overlay_covers_the_whole_screen(blank):
    """An overlay that does not fill the display is not blanking anything.

    The measurement is taken inside the thread that owns Tk, because Tk aborts
    the process if it is called from anywhere else."""
    blank.enable(block_input=False)
    try:
        assert blank.overlay_size is not None, "no overlay window was created"
        assert blank.overlay_covers_the_screen(), (
            f"overlay {blank.overlay_size} does not cover screen {blank.screen_size}"
        )
    finally:
        blank.disable()
    assert blank._root is None


def test_the_watchdog_releases_the_blank_on_its_own():
    """A blank that outlives its session would strand the person at the
    keyboard, so the watchdog is the last line of defence."""
    instance = overlay_only(privacy.PrivacyBlank(watchdog_seconds=1.0))
    try:
        assert instance.enable(block_input=False)["active"] is True
        deadline = time.monotonic() + 8
        while instance.active and time.monotonic() < deadline:
            time.sleep(0.2)
        assert instance.active is False, "the watchdog did not release the blank"
    finally:
        instance.disable()


def test_a_toggled_blank_can_be_re_enabled(blank):
    for _ in range(3):
        assert blank.enable(block_input=False)["active"] is True
        assert blank.disable()["active"] is False
    assert blank.enable(block_input=False)["active"] is True
    blank.disable()
