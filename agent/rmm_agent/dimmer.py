"""Darken the physical display without darkening what the operator sees.

The privacy blank must make the endpoint's own screen go dark while the operator
keeps a live view of the real desktop (specification section 4). A black window
laid over the desktop cannot do that on Linux: the screen capture reads the
desktop as composed, overlay included, so the operator would see black too.

Backlight brightness is applied by the panel AFTER the picture is composed and
captured, so turning the backlight to 0 makes the physical screen go dark while
the captured picture - what the operator sees - is untouched. This works the
same on X11 and on Wayland, because it is below the display server entirely.

Backends, tried in order so this works on any Linux machine at runtime:
  1. brightnessctl - the portable backlight tool; ships a udev rule so it needs
     no root, discovers the device itself, and is a hard dependency of the .deb
     / install.sh so every install has it. Covers laptops (eDP) everywhere.
  2. xrandr --brightness - X11 only, a gamma multiplier that the XShm capture
     reads around; the original method, kept for X11 boxes with no backlight.
  3. (none worked) -> the caller falls back to the guest-lock overlay.

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


def _on_x11() -> bool:
    return bool(shutil.which("xrandr")) and not os.environ.get("WAYLAND_DISPLAY") and bool(
        os.environ.get("DISPLAY")
    )


def backlight_devices(run=_run) -> dict[str, int]:
    """Backlight devices and their current raw brightness, via brightnessctl.

    `brightnessctl -l -m` prints one CSV line per device:
    `name,class,current,percent,max`. We take only class == "backlight" (the
    panel), never keyboards or LEDs.
    """
    found: dict[str, int] = {}
    try:
        # FileNotFoundError here simply means brightnessctl is not installed.
        text = run(["brightnessctl", "-l", "-m"])
    except Exception:
        return {}
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 5 and parts[1] == "backlight":
            try:
                found[parts[0]] = int(parts[2])
            except ValueError:
                pass
    return found


def available() -> bool:
    """Whether this machine can darken its display and keep the picture.

    X11 is judged exactly as before (xrandr); only on Wayland is the backlight
    consulted, so this never changes what X11 reports.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        return bool(backlight_devices())
    return _on_x11()


def parse_outputs(verbose_query: str) -> dict[str, float]:
    """Connected X11 outputs and their current brightness, from `xrandr --verbose`."""
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


class Dimmer:
    """Darkens the connected displays, and always knows how to put them back.

    Tries the backlight first (works on X11 and Wayland, any machine), then the
    X11-only xrandr path. `dim` returns False only if neither could darken
    anything, so the caller can fall back to the overlay lock.
    """

    def __init__(self, run=None, spawn_guard=None) -> None:
        self._run = run or _run
        self._spawn_guard = spawn_guard or _spawn_guard
        # Backlight: device -> raw brightness to restore. xrandr: output -> level.
        self.saved: dict[str, int] = {}
        self.saved_outputs: dict[str, float] = {}
        self._guard = None

    def dim(self, guard_seconds: float) -> bool:
        """Darken the display. False if nothing could be darkened.

        X11 keeps the EXACT path it has always had (xrandr) - that is the
        working Kali behaviour and this change must never alter it. Backlight
        dimming is used ONLY on Wayland, where xrandr cannot help. So on X11
        nothing here runs that did not run before (platform-scope rule).
        """
        if os.environ.get("WAYLAND_DISPLAY"):
            return self._dim_backlight(guard_seconds)
        return self._dim_xrandr(guard_seconds)

    # ---------------------------------------------------------- backlight

    def _dim_backlight(self, guard_seconds: float) -> bool:
        devices = backlight_devices(self._run)
        if not devices:
            return False

        # Arm the safety net first, so there is never a moment where the screen
        # is dark with nothing set to bring it back.
        restore = "; ".join(
            f"brightnessctl -d {shlex.quote(name)} set {level}"
            for name, level in devices.items()
        )
        self._guard = self._spawn_guard(f"sleep {int(guard_seconds)}; {restore}")

        for name, level in devices.items():
            try:
                self._run(["brightnessctl", "-d", name, "set", "0"])
                self.saved[name] = level
            except Exception as exc:
                log.warning("could not darken backlight %s: %s", name, exc)

        if not self.saved:
            self._stop_guard()
            return False
        log.info("darkened backlight %s", ", ".join(self.saved))
        return True

    # -------------------------------------------------------------- xrandr

    def _dim_xrandr(self, guard_seconds: float) -> bool:
        try:
            outputs = parse_outputs(self._run(["xrandr", "--verbose", "--query"]))
        except Exception as exc:
            log.warning("could not read the displays: %s", exc)
            return False
        if not outputs:
            return False

        restore = "; ".join(
            f"xrandr --output {shlex.quote(name)} --brightness {level}"
            for name, level in outputs.items()
        )
        self._guard = self._spawn_guard(f"sleep {int(guard_seconds)}; {restore}")

        for name in outputs:
            try:
                self._run(["xrandr", "--output", name, "--brightness", "0"])
                self.saved_outputs[name] = outputs[name]
            except Exception as exc:
                log.warning("could not darken %s: %s", name, exc)

        if not self.saved_outputs:
            self._stop_guard()
            return False
        log.info("darkened %s", ", ".join(self.saved_outputs))
        return True

    # ------------------------------------------------------------- restore

    def restore(self) -> None:
        """Put every darkened display back exactly as it was."""
        for name, level in list(self.saved.items()):
            try:
                self._run(["brightnessctl", "-d", name, "set", str(level)])
            except Exception as exc:
                log.warning("could not restore backlight %s: %s", name, exc)
        self.saved.clear()
        for name, level in list(self.saved_outputs.items()):
            try:
                self._run(["xrandr", "--output", name, "--brightness", str(level)])
            except Exception as exc:
                log.warning("could not restore %s: %s", name, exc)
        self.saved_outputs.clear()
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
