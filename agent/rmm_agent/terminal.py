"""A shell on the endpoint (spec feature: Remote terminal).

POSIX uses a real pty, so interactive programs and colour work. Windows falls
back to pipes around PowerShell, which is enough for command-and-output.
"""
import asyncio
import logging
import os
import platform
import signal
import subprocess
import sys
import threading

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def default_shell() -> list[str]:
    if IS_WINDOWS:
        return ["powershell.exe", "-NoLogo", "-NoProfile"]
    shell = os.environ.get("SHELL") or "/bin/bash"
    return [shell, "-i"]


class RemoteTerminal:
    """One shell process, with output pushed to `on_output` as it arrives."""

    def __init__(self, on_output, loop: asyncio.AbstractEventLoop) -> None:
        self.on_output = on_output
        self.loop = loop
        self.process: subprocess.Popen | None = None
        self._fd: int | None = None
        self._reader: threading.Thread | None = None
        self._closing = False

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def open(self, cols: int = 100, rows: int = 30) -> None:
        if self.running:
            return
        self._closing = False
        command = default_shell()
        log.info("opening a terminal: %s", " ".join(command))

        if IS_WINDOWS:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._reader = threading.Thread(target=self._pump_pipe, daemon=True)
        else:
            import pty

            pid, fd = pty.fork()
            if pid == 0:  # child
                try:
                    os.environ["TERM"] = "xterm-256color"
                    os.execvp(command[0], command)
                finally:
                    os._exit(1)
            self._fd = fd
            self.process = _PidHandle(pid)
            self.resize(cols, rows)
            self._reader = threading.Thread(target=self._pump_pty, daemon=True)

        self._reader.start()

    def _emit(self, text: str) -> None:
        if text:
            self.loop.call_soon_threadsafe(self.on_output, text)

    def _pump_pty(self) -> None:
        while not self._closing and self._fd is not None:
            try:
                data = os.read(self._fd, 8192)
            except OSError:
                break
            if not data:
                break
            self._emit(data.decode("utf-8", "replace"))
        self._emit("\r\n[the shell exited]\r\n")

    def _pump_pipe(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        while not self._closing:
            data = self.process.stdout.read(1)
            if not data:
                break
            chunk = data + (self.process.stdout.read1(8192) if hasattr(self.process.stdout, "read1") else b"")
            self._emit(chunk.decode("utf-8", "replace"))
        self._emit("\r\n[the shell exited]\r\n")

    def write(self, text: str) -> None:
        if not self.running:
            return
        payload = text.encode("utf-8")
        try:
            if IS_WINDOWS:
                assert self.process is not None and self.process.stdin is not None
                self.process.stdin.write(payload)
                self.process.stdin.flush()
            elif self._fd is not None:
                os.write(self._fd, payload)
        except OSError as exc:
            log.debug("terminal write failed: %s", exc)

    def resize(self, cols: int, rows: int) -> None:
        if IS_WINDOWS or self._fd is None:
            return
        try:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception as exc:
            log.debug("terminal resize failed: %s", exc)

    def close(self) -> None:
        self._closing = True
        if self.process is not None:
            try:
                if IS_WINDOWS:
                    self.process.terminate()
                else:
                    os.kill(self.process.pid, signal.SIGHUP)
            except (OSError, ProcessLookupError):
                pass
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self.process = None
        log.info("terminal closed")


class _PidHandle:
    """Gives a pty child the small part of the Popen interface used here."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        try:
            done, _ = os.waitpid(self.pid, os.WNOHANG)
            return None if done == 0 else 0
        except ChildProcessError:
            return 0

    def terminate(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass
