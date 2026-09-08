"""The consent surface on the endpoint.

Spec section 9: nothing is captured outside an active, consented session, and
the user is told when a session starts. The agent asks before it streams, and
the relay refuses to forward frames until the answer is on record.
"""
import logging
import queue
import threading

log = logging.getLogger(__name__)

PROMPT_TITLE = "Remote support session"


def _message(code: str, operator: str | None) -> str:
    who = operator or "A support operator"
    return (
        f"{who} is requesting to view and control this computer.\n\n"
        f"Session code: {code}\n\n"
        "They will see your screen and be able to use your mouse and keyboard "
        "until you end the session.\n\nAllow this session?"
    )


def _ask_with_tk(code: str, operator: str | None, timeout: float) -> bool | None:
    """Show a dialog. Returns None if no GUI toolkit is available."""
    answer: queue.Queue[bool] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:  # no display, or tkinter not installed
            log.debug("tkinter unavailable: %s", exc)
            answer.put(None)  # type: ignore[arg-type]
            return

        try:
            root = tk.Tk()
            root.title(PROMPT_TITLE)
            root.attributes("-topmost", True)
            root.resizable(False, False)

            frame = ttk.Frame(root, padding=20)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=PROMPT_TITLE, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            ttk.Label(
                frame, text=_message(code, operator), wraplength=420, justify="left"
            ).pack(anchor="w", pady=(10, 16))

            buttons = ttk.Frame(frame)
            buttons.pack(anchor="e")

            def decide(value: bool) -> None:
                if answer.empty():
                    answer.put(value)
                root.destroy()

            ttk.Button(buttons, text="Deny", command=lambda: decide(False)).pack(side="left", padx=6)
            allow = ttk.Button(buttons, text="Allow", command=lambda: decide(True))
            allow.pack(side="left")
            allow.focus_set()

            root.protocol("WM_DELETE_WINDOW", lambda: decide(False))
            # An unanswered prompt denies rather than hanging the session.
            root.after(int(timeout * 1000), lambda: decide(False))
            root.update_idletasks()
            width, height = root.winfo_width(), root.winfo_height()
            root.geometry(
                f"+{(root.winfo_screenwidth() - width) // 2}"
                f"+{(root.winfo_screenheight() - height) // 3}"
            )
            root.mainloop()
        except Exception as exc:
            log.debug("consent dialog failed: %s", exc)
            if answer.empty():
                answer.put(None)  # type: ignore[arg-type]

    thread = threading.Thread(target=run, name="consent-dialog", daemon=True)
    thread.start()
    try:
        return answer.get(timeout=timeout + 5)
    except queue.Empty:
        return False


def ask(code: str, operator: str | None = None, timeout: float = 120.0, auto: bool = False) -> bool:
    """Ask the endpoint user to allow the session."""
    if auto:
        log.warning("consent auto-granted (--auto-consent); intended for testing only")
        return True

    result = _ask_with_tk(code, operator, timeout)
    if result is not None:
        log.info("consent %s by the endpoint user", "granted" if result else "denied")
        return result

    # No GUI available: fall back to the terminal the agent was started from.
    print("\n" + "=" * 60)
    print(PROMPT_TITLE)
    print(_message(code, operator))
    print("=" * 60)
    try:
        reply = input("Allow this session? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        reply = ""
    granted = reply in ("y", "yes")
    log.info("consent %s at the console", "granted" if granted else "denied")
    return granted
