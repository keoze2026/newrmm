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


def own_processes() -> int:
    """How many processes make up this agent. A packaged one-file build is a
    small launcher plus the program it unpacks, and both sit on the console."""
    return 2 if getattr(sys, "frozen", False) else 1


def console_count() -> int | None:
    """How many processes are attached to this console, or None if unknown."""
    if not WINDOWS:
        return None
    try:
        import ctypes

        attached = (ctypes.c_uint * 8)()
        return int(ctypes.windll.kernel32.GetConsoleProcessList(attached, 8))
    except Exception:
        return None


def sole_console_owner(count: int | None, own: int) -> bool:
    """Nothing but the agent is on its console: a double-click or an installer."""
    return count is not None and 0 < count <= own


def shares_console(count: int | None, own: int) -> bool:
    """Something else, a shell, is on the console too."""
    return count is not None and count > own


def free_console() -> None:
    """Let go of the console, so closing its window cannot end the agent."""
    if not WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.FreeConsole()
    except Exception as exc:
        log.debug("could not release the console: %s", exc)


def launched_from_terminal() -> bool:
    """Whether a terminal started this, so there is one for it to be tied to."""
    if WINDOWS:
        return shares_console(console_count(), own_processes())
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
    # A packaged one-file agent unpacks itself into a temporary folder that is
    # deleted when it exits. A child that inherits the packaging environment
    # looks for its files there and dies as soon as this process returns, so
    # the child is told to start clean and unpack its own.
    environment = dict(os.environ)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    # The background copy has no business with any console.
    environment["RMM_BACKGROUND"] = "1"

    options: dict = {
        "env": environment,
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
