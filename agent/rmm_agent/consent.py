"""The consent surface on the endpoint.

Spec section 9: nothing is captured outside an active, consented session, and
the user is told when a session starts. The agent asks before it streams, and
the relay refuses to forward frames until the answer is on record.
"""
import logging
import queue
import sys
import threading

log = logging.getLogger(__name__)

PROMPT_TITLE = "Remote support session"


def _message(code: str, operator: str | None, standing: bool = False) -> str:
    who = operator or "A support operator"
    text = (
        f"{who} is requesting to view and control this computer.\n\n"
        f"Session code: {code}\n\n"
        "They will see your screen and be able to use your mouse and keyboard "
        "until you end the session.\n\nAllow this session?"
    )
    if standing:
        text += (
            "\n\nChoose \"Always allow\" to keep this computer connected, so support can "
            "reach it any time without asking again. You will still see an indicator "
            "and a notice whenever someone connects. You can turn this off from the "
            "tray menu, or by running: rmm-agent stop"
        )
    return text


def _ask_with_tk(
    code: str, operator: str | None, timeout: float, standing: bool = False
) -> "bool | str | None":
    """Show a dialog. True or False, or "always" when `standing` offers it.
    Returns None if no GUI toolkit is available."""
    if sys.platform == "darwin":
        from rmm_agent import macos_dialogs

        return macos_dialogs.consent(_message(code, operator, standing), timeout, standing)

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
                frame, text=_message(code, operator, standing), wraplength=420, justify="left"
            ).pack(anchor="w", pady=(10, 16))

            buttons = ttk.Frame(frame)
            buttons.pack(anchor="e")

            def decide(value) -> None:
                if answer.empty():
                    answer.put(value)
                root.destroy()

            ttk.Button(buttons, text="Deny", command=lambda: decide(False)).pack(side="left", padx=6)
            allow = ttk.Button(
                buttons, text="Allow this time" if standing else "Allow",
                command=lambda: decide(True),
            )
            allow.pack(side="left", padx=(0, 6) if standing else 0)
            allow.focus_set()
            if standing:
                ttk.Button(
                    buttons, text="Always allow", command=lambda: decide("always")
                ).pack(side="left")

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


def ask_choice(
    code: str,
    operator: str | None = None,
    timeout: float = 120.0,
    auto: bool = False,
    standing: bool = False,
) -> str:
    """"deny", "once", or "always". "always" is only offered when `standing`."""
    if auto:
        log.warning("consent auto-granted (--auto-consent); intended for testing only")
        return "once"

    result = _ask_with_tk(code, operator, timeout, standing)
    if result is not None:
        if result == "always":
            log.info("consent granted by the endpoint user, and kept for next time")
            return "always"
        log.info("consent %s by the endpoint user", "granted" if result else "denied")
        return "once" if result else "deny"

    # No GUI available: fall back to the terminal the agent was started from.
    print("\n" + "=" * 60)
    print(PROMPT_TITLE)
    print(_message(code, operator))
    print("=" * 60)
    try:
        reply = input("Allow this session? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt, RuntimeError, OSError) as exc:
        # No terminal to ask (a windowed or background agent has no stdin).
        # Not answering is a refusal; failing here would be retried forever.
        log.warning("no way to ask for consent (%s); treating it as refused", exc)
        reply = ""
    granted = reply in ("y", "yes")
    log.info("consent %s at the console", "granted" if granted else "denied")
    return "once" if granted else "deny"


def ask(code: str, operator: str | None = None, timeout: float = 120.0, auto: bool = False) -> bool:
    """Ask the endpoint user to allow the session."""
    return ask_choice(code, operator, timeout, auto, standing=False) != "deny"
