"""Silent watchdog check: a tiny, windowed-subsystem helper, Windows only.

Built and shipped alongside the main agent as a second executable
(rmm-agent-watchdog.exe), and the only thing the restart watchdog's Scheduled
Task ever launches directly. The main agent is a console-subsystem program by
design (so `rmm-agent status`/`join` etc. still work when typed into a real
terminal), which means Windows allocates a visible console window for it the
instant the process starts - before any of its own code can run to hide it
again. Launching it directly from Task Scheduler flashed that window on
screen every single check, even on the overwhelming majority of checks where
nothing needed fixing.

This program is built as a windowed-subsystem executable instead, so Windows
never creates a window for it at all, under any circumstances. If (and only
if) the main agent actually needs restarting, this launches it the same
already-proven silent way the agent already uses to hand itself off to a
background copy - see background.spawn_detached, which uses the identical
DETACHED_PROCESS | CREATE_NO_WINDOW flags.
"""
import subprocess
import sys
from pathlib import Path

from rmm_agent import background

MAIN_AGENT_NAME = "rmm-agent.exe"


def main() -> int:
    if background.running_pid() is not None:
        return 0

    agent = Path(sys.executable).with_name(MAIN_AGENT_NAME)
    if not agent.exists():
        return 1

    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if background.WINDOWS:
        # Same flags background.spawn_detached already uses, for the same
        # reason: detached from this helper's own (nonexistent) console,
        # its own process group, and - the one that matters here -
        # guaranteed no window, same as this helper's own windowed-subsystem
        # build guarantees for itself.
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen([str(agent), "resume"], **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
