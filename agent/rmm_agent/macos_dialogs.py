"""Dialogs on macOS without Tk.

Tk crashes the agent on macOS. It raises
"-[NSApplication macOSVersion]: unrecognized selector" as soon as a window is
made after the tray library has started the application object, and it must be
used from the main thread, which the tray owns. The consent prompt is the one
dialog an endpoint cannot do without, so on macOS the agent asks through the
system's own `osascript` dialog, which is a separate process and needs neither.
"""
import logging
import subprocess

from rmm_agent.environment import system_environment

log = logging.getLogger(__name__)

TITLE = "Remote support"


def _quote(text: str) -> str:
    """An AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str, timeout: float):
    try:
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout, env=system_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not show a dialog: %s", exc)
        return None


def _cancelled(result) -> bool:
    return "-128" in (result.stderr or "")


def consent(message: str, timeout: float = 120.0, standing: bool = False) -> "bool | str | None":
    """Allow or Deny, or "always" when `standing` offers it. Closing the dialog,
    Deny, or no answer in time is a refusal. None only if no dialog could be
    shown at all."""
    buttons = '{"Deny", "Allow this time", "Always allow"}' if standing else '{"Deny", "Allow"}'
    script = (
        f"display dialog {_quote(message)} with title {_quote(TITLE)} "
        f'buttons {buttons} default button "Deny" with icon caution '
        f"giving up after {int(timeout)}"
    )
    result = _osascript(script, timeout + 15)
    if result is None:
        return None
    if result.returncode != 0:
        return False if _cancelled(result) else None
    out = result.stdout or ""
    if "gave up:false" not in out:
        return False
    if "button returned:Always allow" in out:
        return "always"
    return "button returned:Allow" in out


def ask_code(prefill: str = "", notice: str = "", timeout: float = 600.0) -> str | None:
    """Ask for a session code. None if they cancel; RuntimeError if no dialog
    can be shown, so the caller can fall back to the terminal."""
    text = (notice + "\n\n" if notice else "") + "Enter the code your support technician gave you."
    script = (
        f"display dialog {_quote(text)} default answer {_quote(prefill)} "
        f'with title {_quote(TITLE)} buttons {{"Cancel", "Connect"}} default button "Connect"'
    )
    result = _osascript(script, timeout)
    if result is None:
        raise RuntimeError("no dialog available")
    if result.returncode != 0:
        if _cancelled(result):
            return None
        raise RuntimeError((result.stderr or "dialog failed").strip())
    out = result.stdout or ""
    if "button returned:Connect" not in out or "text returned:" not in out:
        return None
    return out.split("text returned:", 1)[1].split(", gave up:", 1)[0].strip()


def show_error(text: str) -> bool:
    """Tell the person something went wrong. False if it could not be shown."""
    script = (
        f"display dialog {_quote(text)} with title {_quote(TITLE)} "
        'buttons {"OK"} default button "OK" with icon stop'
    )
    result = _osascript(script, 300)
    return result is not None and result.returncode == 0
