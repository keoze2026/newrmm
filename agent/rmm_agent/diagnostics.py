"""Evidence for an agent that dies without saying why.

An agent that crashes inside native code (the capture module is Rust on Windows)
or is closed from outside ends without Python writing a line, so the log just
stops. This leaves three kinds of evidence:

  crash.log   Python stack of every thread when the process takes a fatal error
              (an access violation, a stack overflow, an abort).
  agent.log   "agent exiting" on a normal exit, the Windows console event that
              ended it (window closed, logoff, shutdown), and a "still running"
              line every minute so the time of death is known to the minute.
"""
import atexit
import faulthandler
import logging
import os
import sys
import threading

from rmm_agent.config import state_dir

log = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 60.0

_CONSOLE_EVENTS = {
    0: "Ctrl+C",
    1: "Ctrl+Break",
    2: "the console window was closed",
    5: "the user logged off",
    6: "the computer is shutting down",
}

_keep_alive: list = []  # the Windows callback must outlive this function


def install(directory=None) -> None:
    """Native-crash stacks, an exit line, and Windows console events."""
    directory = directory or state_dir()
    try:
        crash_file = open(directory / "crash.log", "a", buffering=1)
        _keep_alive.append(crash_file)
        faulthandler.enable(file=crash_file, all_threads=True)
    except Exception as exc:  # diagnostics must never stop the agent
        log.debug("crash log unavailable: %s", exc)

    atexit.register(lambda: log.info("agent exiting (process %s)", os.getpid()))

    if sys.platform == "win32":
        _log_console_events()


def _log_console_events() -> None:
    try:
        import ctypes

        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def handler(event):
            log.warning("windows is ending this agent: %s", _CONSOLE_EVENTS.get(event, f"event {event}"))
            return 0  # not handled: the default behaviour carries on

        callback = handler_type(handler)
        _keep_alive.append(callback)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(callback, 1)
    except Exception as exc:
        log.debug("console events unavailable: %s", exc)


def heartbeat(interval: float = HEARTBEAT_SECONDS) -> threading.Event:
    """Log "still running" every `interval` seconds. Set the event to stop."""
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(interval):
            log.info("still running")

    threading.Thread(target=beat, name="heartbeat", daemon=True).start()
    return stop
