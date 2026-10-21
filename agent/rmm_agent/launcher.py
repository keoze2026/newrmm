"""What a non-technical person sees when they double-click the agent.

Nobody being helped is going to open a terminal and type a command. Double-click
the agent and a small window asks for the code the technician read out, checks
it is a real one before going any further, and then the consent dialog takes
over. The server address is built into the agent, so there is nothing else to
type; a build without one asks for it once and remembers it.

Everything that can be decided without a window is a plain function so it can be
tested; the window itself is a thin layer on top.
"""
import logging
import re
import sys
import time
import threading
import urllib.error
import urllib.request

from rmm_agent import config

log = logging.getLogger(__name__)

TITLE = "Remote support"
PROMPT = "Enter the code your support technician gave you."


def normalise_code(raw: str) -> str:
    """Codes are read aloud and typed by hand: ignore spaces, dashes and case."""
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


def to_http(relay: str) -> str:
    relay = relay.strip().rstrip("/")
    if relay.startswith("wss://"):
        return "https://" + relay[len("wss://"):]
    if relay.startswith("ws://"):
        return "http://" + relay[len("ws://"):]
    return relay


def to_ws(server: str) -> str:
    """Turn whatever a person typed into the relay's WebSocket address.

    A bare domain is the likeliest thing to be typed, so that is what makes
    sense: `support.example.com` becomes `wss://support.example.com/api`.
    """
    value = server.strip().rstrip("/")
    if not value:
        return ""
    if value.startswith("https://"):
        value = "wss://" + value[len("https://"):]
    elif value.startswith("http://"):
        value = "ws://" + value[len("http://"):]
    elif not value.startswith(("wss://", "ws://")):
        value = "wss://" + value
    if not re.search(r"/api$", value):
        value += "/api"
    return value


RATE_LIMITED = "Too many attempts. Wait a minute and try again."
# A refusal for asking too often passes by itself, so wait it out quietly rather
# than put an error in front of someone who has done nothing wrong.
RATE_LIMIT_TRIES = 4
RATE_LIMIT_WAIT = 15.0


def check_code(relay: str, code: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Ask the server whether a code is real, in words a person can act on."""
    if len(code) < 4:
        return False, "That code looks too short. Check it and try again."

    url = f"{to_http(relay)}/connector/session/{code}"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, "That code is not valid, or it has expired. Ask your technician for a new one."
        if exc.code == 429:
            return False, RATE_LIMITED
        return False, f"The support server had a problem ({exc.code}). Try again in a moment."
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, "Cannot reach the support server. Check your internet connection."


def hide_console_if_owned() -> None:
    """Hide the black console window when the agent was double-clicked.

    A person who double-clicked an .exe does not want a terminal behind the
    friendly window. But when it was started *from* a terminal, hiding the
    console would hide their own terminal, so this only acts when the agent is
    the sole process attached to it - which is what a double-click looks like.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from rmm_agent import background

        count = background.console_count()
        if background.sole_console_owner(count, background.own_processes()):
            window = ctypes.windll.kernel32.GetConsoleWindow()
            if window:
                ctypes.windll.user32.ShowWindow(window, 0)
            # Hidden is not enough: closing it, or Windows closing it, would
            # still end the agent. A background agent needs no console at all.
            background.free_console()
    except Exception as exc:
        log.debug("could not hide the console: %s", exc)


def resolve(default_relay: str | None, code: str = "") -> tuple[str, str] | None:
    """Get to a verified (code, relay), with as little typing as possible.

    A code that arrived with the download is tried first and, if the server
    accepts it, the person sees no window at all - only the consent dialog. A
    code that has expired, or none, falls back to asking, with the reason shown
    so they know what to do.
    """
    code = normalise_code(code)
    notice = ""
    if code and default_relay:
        for attempt in range(RATE_LIMIT_TRIES):
            ok, notice = check_code(default_relay, code)
            if ok:
                return code, default_relay
            if notice != RATE_LIMITED or attempt == RATE_LIMIT_TRIES - 1:
                break
            time.sleep(RATE_LIMIT_WAIT)
    return ask(default_relay, prefill=code, notice=notice)


def ask(default_relay: str | None, prefill: str = "", notice: str = "") -> tuple[str, str] | None:
    """Ask for a code (and a server, if none is known). None if they cancel."""
    try:
        return _ask_with_window(default_relay, prefill, notice)
    except Exception as exc:
        log.info("no window available (%s); asking in the terminal", exc)
        return _ask_in_terminal(default_relay)


def _ask_in_terminal(default_relay: str | None) -> tuple[str, str] | None:
    relay = default_relay or to_ws(input("Server address: "))
    while True:
        try:
            code = normalise_code(input(f"{PROMPT} "))
        except (EOFError, KeyboardInterrupt):
            return None
        if not code:
            return None
        ok, message = check_code(relay, code)
        if ok:
            return code, relay
        print(message)


def _ask_with_macos_dialog(relay: str, prefill: str, notice: str) -> tuple[str, str] | None:
    """The same question as the window, through macOS's own dialog (no Tk)."""
    from rmm_agent import macos_dialogs

    for _ in range(10):
        answer = macos_dialogs.ask_code(prefill, notice)
        if answer is None:
            return None
        code = normalise_code(answer)
        if not code:
            notice = "Type the code your technician gave you."
            continue
        ok, message = check_code(relay, code)
        if ok:
            return code, relay
        prefill, notice = code, message
    return None


def _ask_with_window(
    default_relay: str | None, prefill: str = "", notice: str = ""
) -> tuple[str, str] | None:
    if sys.platform == "darwin" and default_relay:
        return _ask_with_macos_dialog(default_relay, prefill, notice)

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(TITLE)
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    result: dict[str, tuple[str, str] | None] = {"value": None}
    needs_server = not default_relay

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text=TITLE, font=("Segoe UI", 15, "bold")).pack(anchor="w")
    ttk.Label(frame, text=PROMPT, wraplength=340, justify="left").pack(anchor="w", pady=(6, 14))

    code_var = tk.StringVar(value=normalise_code(prefill))
    entry = ttk.Entry(frame, textvariable=code_var, font=("Consolas", 20), width=14, justify="center")
    entry.pack(fill="x")

    server_var = tk.StringVar(value=config.saved_relay() or "")
    if needs_server:
        ttk.Label(frame, text="Support server", foreground="#6b7a90").pack(anchor="w", pady=(14, 2))
        ttk.Entry(frame, textvariable=server_var).pack(fill="x")

    message = tk.StringVar(value=notice)
    ttk.Label(frame, textvariable=message, foreground="#b42318", wraplength=340,
              justify="left").pack(anchor="w", pady=(12, 0))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(16, 0))
    connect = ttk.Button(buttons, text="Connect")
    connect.pack(side="right")
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right", padx=(0, 8))

    def keep_upper(*_args) -> None:
        cleaned = normalise_code(code_var.get())[:16]
        if cleaned != code_var.get():
            code_var.set(cleaned)

    code_var.trace_add("write", keep_upper)

    def finish(ok: bool, text: str, code: str, relay: str) -> None:
        connect.config(state="normal", text="Connect")
        if ok:
            result["value"] = (code, relay)
            root.destroy()
        else:
            message.set(text)

    def submit(_event=None) -> None:
        code = normalise_code(code_var.get())
        relay = default_relay or to_ws(server_var.get())
        if not code:
            message.set("Type the code first.")
            return
        if not relay:
            message.set("Type the support server's address.")
            return
        message.set("")
        connect.config(state="disabled", text="Checking…")

        def work() -> None:
            ok, text = check_code(relay, code)
            root.after(0, finish, ok, text, code, relay)

        threading.Thread(target=work, daemon=True).start()

    connect.config(command=submit)
    root.bind("<Return>", submit)

    root.update_idletasks()
    width, height = root.winfo_width(), root.winfo_height()
    root.geometry(
        f"+{(root.winfo_screenwidth() - width) // 2}+{(root.winfo_screenheight() - height) // 3}"
    )
    entry.focus_force()
    root.mainloop()
    return result["value"]


def show_error(text: str) -> None:
    """Tell the person something went wrong, where they will actually see it."""
    if sys.platform == "darwin":
        from rmm_agent import macos_dialogs

        if macos_dialogs.show_error(text):
            return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(TITLE, text)
        root.destroy()
    except Exception:
        print(text, file=sys.stderr)
