"""Clipboard access on the endpoint (spec feature: Clipboard sync).

Uses Tk, which ships with Python on Windows and macOS and needs only python3-tk
on Linux - no extra helper binary such as xclip.

On X11 the clipboard belongs to a live window: whoever sets it must stay running
to serve the content. So a single hidden Tk root is kept alive in its own thread
and every operation is marshalled onto it, rather than creating and destroying a
root per call - which silently loses the contents the moment it exits.
"""
import logging
import queue
import threading

log = logging.getLogger(__name__)

_owner: "_ClipboardOwner | None" = None
_lock = threading.Lock()


class _ClipboardOwner:
    """A hidden Tk root that lives for the life of the agent."""

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.failed: str | None = None
        self._root = None
        self._thread = threading.Thread(target=self._run, name="clipboard", daemon=True)
        self._thread.start()
        self.ready.wait(timeout=10)

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._root = tk.Tk()
            self._root.withdraw()
        except Exception as exc:
            self.failed = str(exc)
            self.ready.set()
            return
        self.ready.set()
        self._root.mainloop()

    def call(self, action, timeout: float = 5.0):
        """Run `action(root)` on the Tk thread and return its result."""
        if self._root is None:
            return None
        answer: queue.Queue = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                answer.put(("ok", action(self._root)))
            except Exception as exc:
                answer.put(("error", exc))

        try:
            self._root.after(0, run)
            kind, value = answer.get(timeout=timeout)
        except (queue.Empty, RuntimeError) as exc:
            log.debug("clipboard call did not complete: %s", exc)
            return None
        if kind == "error":
            log.debug("clipboard operation failed: %s", value)
            return None
        return value


def _get_owner() -> _ClipboardOwner | None:
    global _owner
    with _lock:
        if _owner is None:
            _owner = _ClipboardOwner()
        if _owner.failed:
            log.debug("clipboard unavailable: %s", _owner.failed)
            return None
        return _owner


def available() -> bool:
    return _get_owner() is not None


def get_text() -> str | None:
    owner = _get_owner()
    if owner is None:
        return None

    def action(root):
        try:
            return root.clipboard_get()
        except Exception:
            return ""  # an empty or non-text clipboard is not an error

    return owner.call(action)


def set_text(text: str) -> bool:
    owner = _get_owner()
    if owner is None:
        return False

    def action(root):
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        return True

    return bool(owner.call(action))
