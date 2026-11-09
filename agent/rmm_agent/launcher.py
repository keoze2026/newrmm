"""What a non-technical person goes through after installing the agent.

The code that lets this computer join a session is embedded in the download at
install time, so the person never types anything: they install the agent and
the consent dialog takes over. There is deliberately NO window asking for a
code - the agent uses the code it was given, and nothing else. With no code,
there is nothing to do and the agent stops quietly.

Everything that can be decided without a window is a plain function so it can be
tested.
"""
import logging
import re
import sys
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

TITLE = "Remote support"


def normalise_code(raw: str) -> str:
    """Codes are read aloud and typed by hand: ignore spaces, dashes and case."""
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


def to_http(relay: str) -> str:
    relay = relay.strip().rstrip("/")
    if relay.startswith("wss://"):
        return "https://" + relay[len("wss://"):]
    if relay.startswith("ws://"):
        return "http://" + relay[len("ws://"):]
    return relay


def to_ws(server: str) -> str:
    """Turn whatever a person typed into the relay's WebSocket address.

    A bare domain is the likeliest thing to be typed, so that is what makes
    sense: `support.example.com` becomes `wss://support.example.com/api`.
    """
    value = server.strip().rstrip("/")
    if not value:
        return ""
    if value.startswith("https://"):
        value = "wss://" + value[len("https://"):]
    elif value.startswith("http://"):
        value = "ws://" + value[len("http://"):]
    elif not value.startswith(("wss://", "ws://")):
        value = "wss://" + value
    if not re.search(r"/api$", value):
        value += "/api"
    return value


RATE_LIMITED = "Too many attempts. Wait a minute and try again."


def check_code(relay: str, code: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Ask the server whether a code is real, in words a person can act on."""
    if len(code) < 4:
        return False, "That code looks too short. Check it and try again."

    url = f"{to_http(relay)}/connector/session/{code}"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, "That code is not valid, or it has expired. Ask your technician for a new one."
        if exc.code == 429:
            return False, RATE_LIMITED
        return False, f"The support server had a problem ({exc.code}). Try again in a moment."
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, "Cannot reach the support server. Check your internet connection."


def hide_console_if_owned() -> None:
    """Hide the black console window when the agent was double-clicked.

    A person who double-clicked an .exe does not want a terminal behind it. But
    when it was started *from* a terminal, hiding the console would hide their
    own terminal, so this only acts when the agent is the sole process attached
    to it - which is what a double-click looks like.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from rmm_agent import background

        count = background.console_count()
        if background.sole_console_owner(count, background.own_processes()):
            window = ctypes.windll.kernel32.GetConsoleWindow()
            if window:
                ctypes.windll.user32.ShowWindow(window, 0)
            # Hidden is not enough: closing it, or Windows closing it, would
            # still end the agent. A background agent needs no console at all.
            background.free_console()
    except Exception as exc:
        log.debug("could not hide the console: %s", exc)


def resolve(default_relay: str | None, code: str = "") -> tuple[str, str] | None:
    """Use the code that arrived with the download. No window is ever shown:
    the code is embedded at install time and the person never types one. With
    no code or no server there is nothing to do, so the agent stops quietly.
    """
    code = normalise_code(code)
    if code and default_relay:
        return code, default_relay
    return None


def show_error(text: str) -> None:
    """Tell the person something went wrong, where they will actually see it."""
    if sys.platform == "darwin":
        from rmm_agent import macos_dialogs

        if macos_dialogs.show_error(text):
            return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(TITLE, text)
        root.destroy()
    except Exception:
        print(text, file=sys.stderr)
