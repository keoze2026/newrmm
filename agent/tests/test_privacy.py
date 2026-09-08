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


@pytest.fixture
def blank():
    instance = privacy.PrivacyBlank()
    yield instance
    # Never leave a blank up, whatever the test did.
    instance.disable()


def test_this_platform_reports_a_mode():
    mode = privacy.supported_mode()
    assert mode in (privacy.MODE_EXCLUDED, privacy.MODE_GUEST_LOCK)


def test_linux_is_honest_that_it_can_only_guest_lock():
    """No universal capture-exclusion exists on Linux, so the agent must not
    claim it can hide the operator's work."""
    if sys.platform.startswith("linux"):
        assert privacy.supported_mode() == privacy.MODE_GUEST_LOCK


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
    instance = privacy.PrivacyBlank(watchdog_seconds=1.0)
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
