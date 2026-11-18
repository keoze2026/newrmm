"""macOS App Translocation awareness (macOS only).

When a user downloads a quarantined app and runs it straight from Downloads
without moving it, Gatekeeper runs it from a random, read-only "App
Translocation" mount (``/private/var/folders/.../AppTranslocation/.../rmm-agent.app``)
instead of its real location. ``sys.executable`` is then that random path, which
disappears the moment the app quits - so a LaunchAgent written from there points
at nothing and auto-start silently never works again.

Saved settings are unaffected: they live in ``~/Library/Application
Support/RMMAgent`` (config.state_dir), an absolute home path, not inside the
bundle. The problem is purely the unstable executable path, so the agent detects
translocation and tells the user to move the app to Applications (moving it
clears the quarantine and de-translocates it) rather than writing a broken
auto-start entry.

No-op off macOS.
"""
import logging
import platform
import sys

log = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"

MOVE_TITLE = "Move rmm-agent to Applications"
MOVE_STEPS = (
    "rmm-agent is running from a temporary copy, so it cannot keep itself "
    "running after a restart. Drag rmm-agent to your Applications folder and "
    "open it from there."
)


def is_translocated(executable: str | None = None) -> bool:
    """True if the app is running from a Gatekeeper App Translocation mount.

    The mount path always contains ``/AppTranslocation/`` - the documented,
    stable marker. False off macOS."""
    if not IS_MACOS:
        return False
    path = executable if executable is not None else (sys.executable or "")
    return "/AppTranslocation/" in path


def app_bundle_path(executable: str | None = None) -> str | None:
    """The ``.app`` bundle path from the executable, if it is inside one."""
    path = executable if executable is not None else (sys.executable or "")
    marker = ".app/Contents/MacOS/"
    i = path.find(marker)
    if i == -1:
        return None
    return path[: i + len(".app")]
