"""Running in the background, detached from the terminal that started it.

An agent is meant to run quietly while someone is being helped. One started from
a terminal used to die when that terminal was closed or interrupted, because it
was a child of it. Started from a terminal, the agent now hands itself to a
detached process and returns, so closing the terminal - or pressing Ctrl+C in it
- leaves the session running.

Only a start from a terminal detaches. A double-click has no terminal to be tied
to, and explicit `join` stays in the foreground for scripts and tests.
"""
import logging
import os
import subprocess
import sys

from rmm_agent.config import state_dir

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"


def pid_file():
    return state_dir() / "agent.pid"


def launched_from_terminal() -> bool:
    """Whether a terminal started this, so there is one for it to be tied to."""
    if WINDOWS:
        try:
            import ctypes

            attached = (ctypes.c_uint * 4)()
            # More than one process on the console means a shell is sharing it.
            return ctypes.windll.kernel32.GetConsoleProcessList(attached, 4) > 1
        except Exception:
            return False
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def own_command(args: list[str]) -> list[str]:
    """How to run this same agent again, frozen or not."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "rmm_agent", *args]


def spawn_detached(args: list[str]) -> int:
    """Start the agent again as a process that outlives this terminal."""
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if WINDOWS:
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        # A new session: Ctrl+C and closing the terminal signal the foreground
        # process group, which this is no longer part of.
        options["start_new_session"] = True

    return subprocess.Popen(own_command(args), **options).pid


# ----------------------------------------------------------------- pid file


def write_pid() -> None:
    try:
        pid_file().write_text(str(os.getpid()))
    except OSError as exc:
        log.debug("could not record the process id: %s", exc)


def clear_pid() -> None:
    try:
        if pid_file().read_text().strip() == str(os.getpid()):
            pid_file().unlink()
    except (OSError, ValueError):
        pass


def running_pid() -> int | None:
    """The process id of a running agent, or None."""
    try:
        pid = int(pid_file().read_text().strip())
    except (OSError, ValueError):
        return None

    try:
        import psutil

        if not psutil.pid_exists(pid):
            return None
        name = psutil.Process(pid).name().lower()
    except Exception:
        return None
    # A recycled process id belongs to something else; do not claim it.
    return pid if ("rmm" in name or "python" in name) else None


def stop(timeout: float = 8.0) -> bool:
    """Ask a running agent to stop. True if there was one and it is gone."""
    pid = running_pid()
    if pid is None:
        return False
    try:
        import psutil

        process = psutil.Process(pid)
        process.terminate()
        process.wait(timeout=timeout)
    except Exception as exc:
        log.warning("could not stop process %s: %s", pid, exc)
        return False
    try:
        pid_file().unlink()
    except OSError:
        pass
    return True
