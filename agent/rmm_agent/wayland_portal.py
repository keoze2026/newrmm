"""Screen share and remote input on Linux Wayland, through the XDG desktop
portal (org.freedesktop.portal.ScreenCast + RemoteDesktop).

Wayland lets no process read the screen or inject input directly - that is
its security model, and why the X11 module (rmm_capture_linux.c) and pynput's
XTest backend see only a black XWayland root window there. The portal is the
one door every compositor (GNOME, KDE, wlroots, ...) opens: the compositor
shows its own dialog, and only after the person approves does the app get a
PipeWire video stream and permission to send pointer/keyboard events.

The portal work itself runs in `wayland_helper.py`, started with the
machine's own python3 (see that file for why: the system's PyGObject,
GStreamer and PipeWire always match each other and the running PipeWire
daemon; copies bundled into the agent did not, and CI could not even build
them). This module starts that helper, talks to it, and gives the rest of the
agent the same small interface it always had.
"""
import json
import logging
import os
import select
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# Linux evdev button codes (linux/input-event-codes.h) - what
# NotifyPointerButton expects, not a browser/X11 button number.
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

# X11 keysyms (X11/keysymdef.h) for NotifyKeyboardKeysym.
KEYSYMS = {
    "Enter": 0xFF0D, "Backspace": 0xFF08, "Tab": 0xFF09, "Escape": 0xFF1B,
    "Delete": 0xFFFF, "Home": 0xFF50, "End": 0xFF57,
    "PageUp": 0xFF55, "PageDown": 0xFF56,
    "ArrowUp": 0xFF52, "ArrowDown": 0xFF54, "ArrowLeft": 0xFF51, "ArrowRight": 0xFF53,
    "Shift": 0xFFE1, "Control": 0xFFE3, "Alt": 0xFFE9, "Meta": 0xFFEB,
    "CapsLock": 0xFFE5, " ": 0x0020, "Insert": 0xFF63,
    "F1": 0xFFBE, "F2": 0xFFBF, "F3": 0xFFC0, "F4": 0xFFC1,
    "F5": 0xFFC2, "F6": 0xFFC3, "F7": 0xFFC4, "F8": 0xFFC5,
    "F9": 0xFFC6, "F10": 0xFFC7, "F11": 0xFFC8, "F12": 0xFFC9,
}

# How long the person may take over the compositor's own dialog.
START_TIMEOUT = 200.0
RESTORE_TOKEN_FILE = "wayland_restore_token"


def keysym_for(name: str) -> int | None:
    """Browser key name -> X11 keysym, for NotifyKeyboardKeysym."""
    if name in KEYSYMS:
        return KEYSYMS[name]
    if len(name) == 1:
        code = ord(name)
        # Latin-1 keysyms equal their code point; everything above is the
        # Unicode keysym range (keysymdef.h: 0x01000000 + code point).
        return code if code <= 0xFF else 0x01000000 | code
    return None


def session_is_wayland(env=None) -> bool:
    """Whether this desktop is Wayland.

    WAYLAND_DISPLAY alone is not enough: an agent started by the systemd user
    service at login only sees it if the desktop exported it to systemd, and
    several do not. Missing it means trying X11 capture on XWayland, which
    "works" and returns black frames. The session type and the compositor's
    socket are checked too.
    """
    env = os.environ if env is None else env
    if env.get("WAYLAND_DISPLAY"):
        return True
    if env.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    if not env.get("DISPLAY"):
        runtime = env.get("XDG_RUNTIME_DIR")
        if runtime:
            try:
                return any(
                    p.name.startswith("wayland-") and not p.name.endswith(".lock")
                    for p in Path(runtime).iterdir()
                )
            except OSError:
                return False
    return False


def helper_path() -> Path:
    return Path(__file__).with_name("wayland_helper.py")


def system_python() -> str | None:
    """The distribution's python3 - the one its python3-gi belongs to."""
    override = os.environ.get("RMM_SYSTEM_PYTHON")
    if override:
        return override
    for candidate in ("/usr/bin/python3", "/usr/local/bin/python3", "/bin/python3"):
        if os.access(candidate, os.X_OK):
            return candidate
    from rmm_agent.environment import system_environment

    return shutil.which("python3", path=system_environment().get("PATH"))


def _helper_env() -> dict:
    from rmm_agent.environment import system_environment

    env = system_environment()
    # A frozen agent's own Python settings must not leak into the system one.
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "RMM_BACKGROUND",
                 "PYINSTALLER_RESET_ENVIRONMENT", "GST_PLUGIN_PATH",
                 "GST_PLUGIN_SYSTEM_PATH", "GI_TYPELIB_PATH", "GIO_MODULE_DIR"):
        env.pop(name, None)
    return env


def diagnose() -> dict:
    """What this machine can do for Wayland, as the helper sees it."""
    python = system_python()
    if not helper_path().exists():
        return {"error": "the Wayland helper is missing from this build"}
    if not python:
        return {"error": "no system python3 found"}
    try:
        result = subprocess.run(
            [python, "-I", str(helper_path()), "--check"],
            capture_output=True, text=True, timeout=20, env=_helper_env(),
        )
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {"python": python, "error": f"helper check failed: {exc}"}


def load_restore_token() -> str | None:
    from rmm_agent.config import state_dir

    try:
        token = (state_dir() / RESTORE_TOKEN_FILE).read_text().strip()
        return token or None
    except OSError:
        return None


def save_restore_token(token: str) -> None:
    from rmm_agent import durable
    from rmm_agent.config import state_dir

    path = state_dir() / RESTORE_TOKEN_FILE
    try:
        durable.write_text(path, token)
        os.chmod(path, 0o600)
    except OSError as exc:
        log.warning("could not keep the Wayland screen-share permission: %s", exc)


def forget_restore_token() -> None:
    from rmm_agent.config import state_dir

    try:
        (state_dir() / RESTORE_TOKEN_FILE).unlink(missing_ok=True)
    except OSError:
        pass


class PortalSession:
    """One portal screen share (plus input, when the portal grants it),
    owned by a helper process running under the system python3.

    Every method is safe to call on a session that never started or has
    closed: it does nothing, so teardown never has to check first."""

    def __init__(self) -> None:
        self.python = system_python() if sys.platform.startswith("linux") else None
        self.available = bool(self.python and helper_path().exists())
        self.started = False
        self.input_available = False
        self.monitors: list[dict] = []
        self.restore_token: str | None = None
        self.denied = False
        self.error: str | None = None
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._grab_lock = threading.Lock()
        self._last: tuple[bytes, int, int] | None = None
        self._buffer = bytearray()

    # ------------------------------------------------------------ lifecycle

    def start(self, want_input: bool = True, restore_token: str | None = None,
              persist_mode: int = 0, timeout: float = START_TIMEOUT) -> bool:
        """Ask the compositor for the screen (and input). Blocks until the
        person answers its dialog. Returns False, never raises."""
        if not self.available:
            self.error = "no system python3 or helper"
            return False
        try:
            self._proc = subprocess.Popen(
                [self.python, "-I", str(helper_path())],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=_helper_env(), close_fds=True, bufsize=0,
            )
            self._buffer = bytearray()
        except OSError as exc:
            self.error = f"could not start the Wayland helper: {exc}"
            log.warning(self.error)
            return False
        threading.Thread(target=self._drain_stderr, name="wayland-helper-log", daemon=True).start()
        try:
            self._write({"want_input": bool(want_input), "persist_mode": int(persist_mode),
                         "restore_token": restore_token})
            kind, payload = self._read(timeout)
            if kind != b"J":
                raise RuntimeError(f"unexpected first reply {kind!r}")
            message = json.loads(payload)
        except Exception as exc:
            self.error = f"the Wayland helper did not answer: {exc}"
            log.warning(self.error)
            self.close()
            return False
        if message.get("event") != "ready":
            self.denied = bool(message.get("denied"))
            self.error = message.get("detail") or "the portal share failed"
            log.warning("Wayland screen share did not start: %s", self.error)
            self.close()
            return False
        self.monitors = [dict(m) for m in message.get("monitors") or []]
        self.input_available = bool(message.get("input"))
        self.restore_token = message.get("restore_token")
        self.started = True
        log.info(
            "Wayland portal share started (%s, input %s)",
            ", ".join(f"{m['width']}x{m['height']}" for m in self.monitors) or "?",
            "granted" if self.input_available else "not available",
        )
        return True

    def close(self) -> None:
        proc, self._proc = self._proc, None
        self.started = False
        self.input_available = False
        if proc is None:
            return
        try:
            if proc.poll() is None:
                with self._write_lock:
                    proc.stdin.write(b'{"op": "close"}\n')
                    proc.stdin.flush()
                proc.wait(timeout=3)
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------ pipes

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None:
            return
        for line in proc.stderr:
            text = line.decode(errors="replace").rstrip()
            if text:
                log.info("wayland helper: %s", text)

    def _write(self, obj: dict) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError("the Wayland helper is not running")
        with self._write_lock:
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()

    def _read_exact(self, size: int, timeout: float | None) -> bytes:
        """Exactly `size` bytes from the helper. Reads the raw pipe with its
        own buffer, so select() never misses data already read ahead."""
        proc = self._proc
        if proc is None:
            raise RuntimeError("the Wayland helper is not running")
        fd = proc.stdout.fileno()
        while len(self._buffer) < size:
            if timeout is not None:
                ready, _, _ = select.select([fd], [], [], timeout)
                if not ready:
                    raise TimeoutError("the Wayland helper did not reply in time")
            chunk = os.read(fd, max(1 << 20, size - len(self._buffer)))
            if not chunk:
                raise RuntimeError("the Wayland helper exited")
            self._buffer += chunk
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _read(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        header = self._read_exact(5, timeout)
        kind = header[:1]
        (length,) = struct.unpack("<I", header[1:])
        return kind, self._read_exact(length, timeout) if length else b""

    # ------------------------------------------------------------ capture

    def grab(self, timeout: float = 10.0) -> tuple[bytes, int, int]:
        """The newest frame as packed RGB. A still screen returns the last
        frame again rather than failing - PipeWire only sends on change."""
        if not self.started:
            raise RuntimeError("the Wayland screen share is not running")
        with self._grab_lock:
            self._write({"op": "grab"})
            kind, payload = self._read(timeout)
        if kind == b"F":
            width, height = struct.unpack("<II", payload[:8])
            self._last = (payload[8:], width, height)
        elif kind == b"S":
            if self._last is None:
                raise RuntimeError("no picture from the Wayland screen share yet")
        else:
            raise RuntimeError(payload.decode(errors="replace") or "the Wayland screen share ended")
        return self._last

    # ------------------------------------------------------------ input
    # Fire-and-forget: the helper never answers these, so they cannot
    # interleave with a grab's reply.

    def _send_input(self, obj: dict) -> None:
        if not (self.started and self.input_available):
            return
        try:
            self._write(obj)
        except Exception as exc:
            log.debug("could not send Wayland input: %s", exc)

    def notify_pointer_motion_absolute(self, x: float, y: float) -> None:
        """x/y in the shared stream's own space: 0..width, 0..height."""
        self._send_input({"op": "motion", "x": float(x), "y": float(y)})

    def notify_pointer_button(self, button: int, pressed: bool) -> None:
        self._send_input({"op": "button", "button": int(button), "pressed": bool(pressed)})

    def notify_pointer_axis_discrete(self, vertical: bool, steps: int) -> None:
        """Positive steps scroll down, as Wayland's own axis does."""
        if steps and vertical:
            self._send_input({"op": "axis", "steps": int(steps)})

    def notify_keyboard_keysym(self, keysym: int, pressed: bool) -> None:
        self._send_input({"op": "key", "keysym": int(keysym), "pressed": bool(pressed)})
