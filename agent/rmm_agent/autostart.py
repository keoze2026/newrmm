"""Starting again after the computer restarts.

An agent started with a session code used to end when the computer restarted,
and nothing brought it back. The specification lists auto-start for every
platform (section 5, "Auto-start"); on Linux it is a systemd user service.

The agent remembers the session it joined and turns the packaged
`rmm-agent-resume` user service on. At the next login the service runs
`rmm-agent resume`, which rejoins that session. Consent is still asked each
time, because it is a new boot and nobody has agreed to this one yet.

It turns itself off again when the session is over, when consent is refused,
and when the person ends it (`rmm-agent stop` or the tray's Quit). A shutdown
is none of those, so it does not.
"""
import json
import logging
import shutil
import subprocess
import sys

from rmm_agent.config import state_dir

log = logging.getLogger(__name__)

UNIT = "rmm-agent-resume.service"


def session_file():
    return state_dir() / "session.json"


def _systemctl(*arguments: str) -> bool:
    if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", *arguments],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not run systemctl: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("systemctl %s failed: %s", " ".join(arguments), result.stderr.strip())
    return result.returncode == 0


def saved() -> tuple[str, str] | None:
    """The (relay, code) to rejoin, or None."""
    try:
        data = json.loads(session_file().read_text())
        return data["relay"], data["code"]
    except (OSError, ValueError, KeyError):
        return None


def remember(relay: str, code: str, enable=_systemctl) -> bool:
    """Remember this session and start again at login. False if it cannot."""
    try:
        session_file().write_text(json.dumps({"relay": relay, "code": code}))
    except OSError as exc:
        log.warning("could not remember the session: %s", exc)
        return False
    return enable("enable", UNIT)


def forget(code: str | None = None, disable=_systemctl) -> None:
    """Stop starting at login. With a code, only if it is the remembered one."""
    current = saved()
    if current is None:
        return
    if code is not None and current[1] != code:
        return
    try:
        session_file().unlink()
    except OSError:
        pass
    disable("disable", UNIT)
