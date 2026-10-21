"""Darken the physical display without darkening what the operator sees.

The privacy blank is meant to make the endpoint's own screen go dark while the
operator keeps a live view of the real desktop (specification section 4). A
black window laid over the desktop cannot do that on Linux: the screen capture
reads the desktop as composed, overlay included, so the operator sees black too.

Brightness is applied later, when the picture is sent to the monitor, so the
captured picture is untouched. Setting every connected output's brightness to 0
makes the monitor dark while the operator still sees the real screen.

That setting persists if the agent dies, so a dead man's switch is started in
its own process: a few seconds past the longest the blank may last it restores
the brightness whatever happened to the agent.
"""
import logging
import os
import re
import shlex
import shutil
import subprocess

from rmm_agent.environment import system_environment

log = logging.getLogger(__name__)

_OUTPUT = re.compile(r"^(\S+) connected\b")
_BRIGHTNESS = re.compile(r"^\s+Brightness:\s*([0-9.]+)")


def available() -> bool:
    """Only on X11 with xrandr: Wayland compositors own their own brightness."""
    if not shutil.which("xrandr"):
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return False
    return bool(os.environ.get("DISPLAY"))


def parse_outputs(verbose_query: str) -> dict[str, float]:
    """Connected outputs and their current brightness, from `xrandr --verbose`."""
    found: dict[str, float] = {}
    current: str | None = None
    for line in verbose_query.splitlines():
        match = _OUTPUT.match(line)
        if match:
            current = match.group(1)
            found[current] = 1.0
            continue
        if line and not line[0].isspace():
            current = None
            continue
        bright = _BRIGHTNESS.match(line)
        if bright and current is not None:
            try:
                found[current] = float(bright.group(1))
            except ValueError:
                pass
    return found


def _run(command: list[str]) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=10, env=system_environment()
    )
    return result.stdout


def _spawn_guard(command: str) -> "subprocess.Popen | None":
    """A shell that outlives the agent and puts the brightness back."""
    try:
        return subprocess.Popen(
            ["sh", "-c", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=system_environment(),
            start_new_session=True,
        )
    except OSError as exc:
        log.warning("could not start the brightness safety net: %s", exc)
        return None


class Dimmer:
    """Darkens the connected displays, and always knows how to put them back."""

    def __init__(self, run=None, spawn_guard=None) -> None:
        self._run = run or _run
        self._spawn_guard = spawn_guard or _spawn_guard
        self.saved: dict[str, float] = {}
        self._guard = None

    def dim(self, guard_seconds: float) -> bool:
        """Darken every connected output. False if nothing could be darkened."""
        try:
            outputs = parse_outputs(self._run(["xrandr", "--verbose", "--query"]))
        except Exception as exc:
            log.warning("could not read the displays: %s", exc)
            return False
        if not outputs:
            return False

        # Arm the safety net first, so there is no moment where the screen is
        # dark and nothing is set to bring it back.
        restore = "; ".join(
            f"xrandr --output {shlex.quote(name)} --brightness {level}"
            for name, level in outputs.items()
        )
        self._guard = self._spawn_guard(f"sleep {int(guard_seconds)}; {restore}")

        for name in outputs:
            try:
                self._run(["xrandr", "--output", name, "--brightness", "0"])
                self.saved[name] = outputs[name]
            except Exception as exc:
                log.warning("could not darken %s: %s", name, exc)

        if not self.saved:
            self._stop_guard()
            return False
        log.info("darkened %s", ", ".join(self.saved))
        return True

    def restore(self) -> None:
        """Put every darkened output back exactly as it was."""
        for name, level in list(self.saved.items()):
            try:
                self._run(["xrandr", "--output", name, "--brightness", str(level)])
            except Exception as exc:
                log.warning("could not restore %s: %s", name, exc)
        self.saved.clear()
        self._stop_guard()

    def _stop_guard(self) -> None:
        guard, self._guard = self._guard, None
        if guard is not None:
            try:
                guard.terminate()
            except Exception:
                pass


def escape_counter(escape_key, on_escape, clock, presses: int = 3, window: float = 2.0):
    """A key callback that releases the blank after Escape is pressed quickly.

    With no overlay there is nothing on screen to say how to get out, so a way
    out that needs no knowledge: press Escape three times. A single press would
    be too easy to hit by accident, including by the operator.
    """
    recent: list[float] = []

    def on_press(key):
        if key != escape_key:
            return None
        now = clock()
        recent[:] = [t for t in recent if now - t <= window]
        recent.append(now)
        if len(recent) >= presses:
            recent.clear()
            on_escape()
        return None

    return on_press
