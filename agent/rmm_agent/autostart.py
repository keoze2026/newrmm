"""Starting again after the computer restarts.

An agent started with a session code used to end when the computer restarted,
and nothing brought it back. The specification lists auto-start for every
platform (section 5, "Auto-start"); on Linux it is a systemd user service.

Every platform has its own mechanism, as the specification lists:

  Linux    the packaged `rmm-agent-resume` systemd user service
  Windows  a per-user Run entry (no administrator needed)
  macOS    a LaunchAgent in ~/Library/LaunchAgents

The agent remembers the session it joined and turns that on. At the next login the service runs
`rmm-agent resume`, which rejoins that session. Consent is still asked each
time, because it is a new boot and nobody has agreed to this one yet.

It turns itself off again when the session is over, when consent is refused,
and when the person ends it (`rmm-agent stop` or the tray's Quit). A shutdown
is none of those, so it does not.
"""
import json
import logging
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from rmm_agent import background, durable
from rmm_agent.config import state_dir
from rmm_agent.environment import system_environment

log = logging.getLogger(__name__)

UNIT = "rmm-agent-resume.service"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RMMAgentResume"
MAC_LABEL = "com.rmm.agent.resume"
WATCHDOG_TASK = "RMMAgentWatchdog"


def session_file():
    return state_dir() / "session.json"


def _systemctl(*arguments: str) -> bool:
    if not sys.platform.startswith("linux") or not shutil.which("systemctl"):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", *arguments],
            capture_output=True, text=True, timeout=15,
            env=system_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not run systemctl: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("systemctl %s failed: %s", " ".join(arguments), result.stderr.strip())
    return result.returncode == 0


def _resume_command() -> list[str]:
    return background.own_command(["resume"])


def _windows_enable() -> bool:
    try:
        import winreg

        command = subprocess.list2cmdline(_resume_command())
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    except Exception as exc:
        log.warning("could not turn on starting at login: %s", exc)
        return False
    _windows_enable_watchdog()
    return True


def _windows_disable() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("could not turn off starting at login: %s", exc)
        return False
    _windows_disable_watchdog()
    return True


def _windows_enable_watchdog() -> bool:
    """A Scheduled Task that notices if the agent is gone and starts it again.

    The Run key above only fires once, at login. Nothing otherwise brings the
    agent back if it is ever killed - by a crash, by something else on the
    machine, by anything - without someone noticing and starting it by hand.
    This checks every couple of minutes, forever, independent of why it died.
    `resume` is safe to call blindly like this: it is a no-op when the agent
    is already running (see cmd_resume).
    """
    try:
        command = subprocess.list2cmdline(_resume_command())
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", WATCHDOG_TASK, "/TR", command,
             "/SC", "MINUTE", "/MO", "2", "/F"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            log.warning("could not turn on the restart watchdog: %s", result.stderr.strip())
            return False
        return True
    except Exception as exc:
        log.warning("could not turn on the restart watchdog: %s", exc)
        return False


def _windows_disable_watchdog() -> None:
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", WATCHDOG_TASK, "/F"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:
        log.debug("could not remove the restart watchdog: %s", exc)


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _mac_enable() -> bool:
    try:
        path = _mac_plist()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            plistlib.dumps(
                {
                    "Label": MAC_LABEL,
                    "ProgramArguments": _resume_command(),
                    "RunAtLoad": True,
                    "LimitLoadToSessionType": "Aqua",
                }
            )
        )
        return True
    except Exception as exc:
        log.warning("could not turn on starting at login: %s", exc)
        return False


def _mac_disable() -> bool:
    try:
        _mac_plist().unlink(missing_ok=True)
    except Exception as exc:
        log.warning("could not turn off starting at login: %s", exc)
        return False
    return True


def _enable_here() -> bool:
    if sys.platform == "win32":
        return _windows_enable()
    if sys.platform == "darwin":
        return _mac_enable()
    return _systemctl("enable", UNIT)


def _disable_here() -> bool:
    if sys.platform == "win32":
        return _windows_disable()
    if sys.platform == "darwin":
        return _mac_disable()
    return _systemctl("disable", UNIT)


def saved() -> tuple[str, str] | None:
    """The (relay, code) to rejoin, or None."""
    try:
        text = session_file().read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("could not read the saved session: %s", exc)
        return None
    try:
        data = json.loads(text)
        return data["relay"], data["code"]
    except (ValueError, KeyError):
        log.warning("the saved session file is empty or damaged (%d bytes); nothing to rejoin", len(text))
        return None


def remember(relay: str, code: str, enable=None) -> bool:
    """Remember this session and start again at login. False if it cannot."""
    try:
        durable.write_text(session_file(), json.dumps({"relay": relay, "code": code}))
    except OSError as exc:
        log.warning("could not remember the session: %s", exc)
        return False
    return enable("enable", UNIT) if enable else _enable_here()


def forget(code: str | None = None, disable=None, always: bool = False) -> None:
    """Stop starting at login. With a code, only if it is the remembered one."""
    current = saved()
    if current is None and not always:
        return
    if current is not None and code is not None and current[1] != code:
        return
    try:
        session_file().unlink()
    except OSError:
        pass
    if disable:
        disable("disable", UNIT)
    else:
        _disable_here()
