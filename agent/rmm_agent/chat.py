"""A small chat window shown to the endpoint user during a session, so they
can talk to the operator without picking up a phone.

Created the first time a chat message arrives for the session and torn down
when the session ends (`AgentSession._close_tools`) - the same lifecycle as
the terminal and the privacy blank, not something that needs its own
open/close protocol message, since there is no resource here beyond the
window itself.

All windows share one persistent background thread and one `tk.Tk()` root
for the life of the process, created lazily on first use and never torn
down. An always-on device keeps one process running across many sessions, so
a naive "new thread, new Tk() per window" design - closing one window's root
and later creating a fresh one on a different thread - hit a real Tcl
limitation (confirmed outside this codebase too): a second `Tk()` created on
a second thread later in the same process crashed the whole process outright
on Windows with "Tcl_AsyncDelete: async handler deleted by the wrong
thread". One root, reused as a parent for a `Toplevel` per window, avoids
ever creating a second interpreter.
"""
import logging
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)

TITLE = "Chat with support"

_commands: "queue.Queue[tuple]" = queue.Queue()
_gui_thread: threading.Thread | None = None
_gui_lock = threading.Lock()
_gui_available = threading.Event()
_gui_unavailable = threading.Event()
# Set once the GUI thread has decided either way, so a caller waits only as
# long as that takes. Waiting on _gui_unavailable alone always ran the full
# timeout when the GUI was fine, stalling the session 3 s per chat window.
_gui_decided = threading.Event()


def _ensure_gui_thread() -> None:
    global _gui_thread
    with _gui_lock:
        if _gui_thread is not None:
            return
        _gui_thread = threading.Thread(target=_gui_main, name="chat-gui", daemon=True)
        _gui_thread.start()


def _gui_main() -> None:
    try:
        import tkinter as tk
    except Exception as exc:  # no display, or tkinter not installed
        log.debug("tkinter unavailable, chat windows disabled: %s", exc)
        _gui_unavailable.set()
        _gui_decided.set()
        return

    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as exc:
        log.debug("could not create the chat GUI root: %s", exc)
        _gui_unavailable.set()
        _gui_decided.set()
        return

    _gui_available.set()
    _gui_decided.set()

    def poll() -> None:
        try:
            while True:
                cmd, window, *rest = _commands.get_nowait()
                try:
                    if cmd == "create":
                        window._build(tk, root)
                    elif cmd == "receive":
                        window._append_incoming(rest[0])
                    elif cmd == "close":
                        window._destroy()
                except Exception as exc:
                    log.debug("chat GUI command %r failed: %s", cmd, exc)
        except queue.Empty:
            pass
        root.after(100, poll)

    root.after(100, poll)
    root.mainloop()


class ChatWindow:
    """A thin handle onto one chat conversation's window. Every call here is
    safe from any thread: nothing touches a Tk widget directly - each method
    only ever queues a command for the single shared GUI thread to run."""

    def __init__(self, on_reply: Callable[[str], None]) -> None:
        self._on_reply = on_reply
        self._toplevel = None
        self._history = None
        self._closed = threading.Event()
        _ensure_gui_thread()
        _gui_decided.wait(timeout=3.0)
        self.available = not _gui_unavailable.is_set()
        if self.available:
            _commands.put(("create", self))
        else:
            self._closed.set()

    def _build(self, tk, root) -> None:
        top = tk.Toplevel(root)
        self._toplevel = top
        top.title(TITLE)
        top.attributes("-topmost", True)
        top.geometry("340x380")
        # Hiding rather than destroying lets the operator keep sending
        # messages even if the endpoint user closes the window - it just
        # pops back up, instead of silently going nowhere.
        top.protocol("WM_DELETE_WINDOW", top.withdraw)

        from tkinter import ttk

        frame = ttk.Frame(top, padding=10)
        frame.pack(fill="both", expand=True)

        # The reply row is packed first, at the bottom, so it always has room.
        # Packed after the history (whose default height is 24 lines), it was
        # pushed off the bottom of the 380 px window: the person could read
        # the operator but had nowhere to type an answer.
        entry_row = ttk.Frame(frame)
        entry_row.pack(side="bottom", fill="x", pady=(8, 0))

        history = tk.Text(frame, state="disabled", wrap="word", height=10)
        history.pack(side="top", fill="both", expand=True)
        self._history = history
        entry = ttk.Entry(entry_row)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()

        def send(*_args) -> None:
            text = entry.get().strip()
            if not text:
                return
            entry.delete(0, "end")
            self._append("You", text)
            self._on_reply(text)

        entry.bind("<Return>", send)
        ttk.Button(entry_row, text="Send", command=send).pack(side="left", padx=(6, 0))

        top.withdraw()  # stay out of the way until the first message arrives

    def _append(self, who: str, text: str) -> None:
        if self._history is None:
            return
        self._history.configure(state="normal")
        self._history.insert("end", f"{who}: {text}\n")
        self._history.configure(state="disabled")
        self._history.see("end")

    def _append_incoming(self, text: str) -> None:
        self._append("Support", text)
        if self._toplevel is not None:
            self._toplevel.deiconify()
            self._toplevel.lift()

    def _destroy(self) -> None:
        if self._toplevel is not None:
            self._toplevel.destroy()
            self._toplevel = None
        self._closed.set()

    def receive(self, text: str) -> None:
        """Called from any thread when the operator sends a message."""
        if self.available:
            _commands.put(("receive", self, text))

    def close(self) -> None:
        if self.available:
            _commands.put(("close", self))
        self._closed.wait(timeout=2.0)
