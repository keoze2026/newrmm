"""The privacy blank (spec section 5).

The guest's own display goes black while the operator keeps working. How that
is achieved differs per platform, because hiding a window from the machine's own
screen capture is an OS graphics-layer operation with no common mechanism:

  Windows   A black always-on-top window marked WDA_EXCLUDEFROMCAPTURE, so the
            compositor keeps it off anything that captures the screen. The
            operator keeps a live view of the desktop behind it, and keeps
            control.

  macOS     The same idea through NSWindowSharingNone, which removes the window
            from captures.

  Linux     No universal capture-exclusion exists, so this is a *guest-lock*
            instead: the screen goes black and local input is blocked, and the
            operator's view goes black too. It locks the machine rather than
            hiding the operator's work. The spec names this as the reliable
            fallback, and the agent reports which of the two it is doing so
            nobody is misled.

No kernel display driver is used anywhere.

Safety: a blank that outlives its session would leave someone staring at a black
screen they cannot dismiss. So every blank is released when the session ends or
the connection drops, and an optional watchdog releases it after a fixed time.
"""
import logging
import platform
import queue
import threading
import time

log = logging.getLogger(__name__)

WINDOWS = platform.system() == "Windows"
MACOS = platform.system() == "Darwin"

# What the endpoint is actually able to do, reported to the operator.
MODE_EXCLUDED = "capture-excluded"  # operator keeps a live view
MODE_GUEST_LOCK = "guest-lock"      # screen locked; the operator sees black too
MODE_UNAVAILABLE = "unavailable"

BANNER = "This screen is locked while a support session is in progress."


def supported_mode() -> str:
    """Which privacy mode this machine can deliver."""
    if WINDOWS:
        return MODE_EXCLUDED
    if MACOS:
        return MODE_EXCLUDED if _has_pyobjc() else MODE_GUEST_LOCK
    return MODE_GUEST_LOCK


def _has_pyobjc() -> bool:
    try:
        import AppKit  # noqa: F401

        return True
    except Exception:
        return False


class PrivacyBlank:
    """Owns the black overlay and, on the guest-lock path, the input block."""

    def __init__(self, watchdog_seconds: float = 0.0) -> None:
        self.watchdog_seconds = watchdog_seconds
        self.mode = supported_mode()
        self.active = False
        self._thread: threading.Thread | None = None
        self._root = None
        self._ready: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._suppressors: list = []
        self._started_at = 0.0
        self.overlay_size: tuple[int, int] | None = None
        self.screen_size: tuple[int, int] | None = None

    # ------------------------------------------------------------------ api

    def enable(self, block_input: bool = True) -> dict:
        """Blank the guest's screen. Returns what actually happened."""
        if self.active:
            return self.state()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="privacy-blank", daemon=True)
        self._thread.start()

        try:
            result = self._ready.get(timeout=10)
        except queue.Empty:
            result = "the overlay did not appear"

        if result is not True:
            log.error("privacy blank failed: %s", result)
            self._stop.set()
            return {"active": False, "mode": MODE_UNAVAILABLE, "error": str(result)}

        self.active = True
        self._started_at = time.monotonic()

        if block_input and self.mode == MODE_GUEST_LOCK:
            self._block_local_input()

        if self.watchdog_seconds > 0:
            threading.Thread(target=self._watchdog, name="privacy-watchdog", daemon=True).start()

        log.info("privacy blank on (%s)", self.mode)
        return self.state()

    def disable(self) -> dict:
        if not self.active:
            return self.state()
        self._release_local_input()
        # Tk is not thread-safe, so the overlay is never touched from here: the
        # thread that owns it polls this flag and tears itself down.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log.warning("the overlay thread did not exit; leaving it to close itself")
        self._thread = None
        self.active = False
        log.info("privacy blank off")
        return self.state()

    def state(self) -> dict:
        return {
            "active": self.active,
            "mode": self.mode,
            "input_blocked": bool(self._suppressors),
            "seconds": round(time.monotonic() - self._started_at, 1) if self.active else 0,
        }

    # -------------------------------------------------------------- overlay

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            self._ready.put(f"no GUI toolkit: {exc}")
            return

        root = None
        try:
            root = tk.Tk()
            root.title("Remote support")
            root.configure(bg="black")
            root.attributes("-topmost", True)

            # Ask for the screen size explicitly as well as fullscreen: the
            # -fullscreen attribute is a request to the window manager, and
            # some ignore or defer it. Without the explicit geometry the window
            # can end up at its natural size - a small box that blanks nothing
            # while the blank reports success.
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.geometry(f"{screen_width}x{screen_height}+0+0")
            try:
                root.attributes("-fullscreen", True)
            except Exception:
                root.overrideredirect(True)
            root.config(cursor="none")

            if self.mode == MODE_GUEST_LOCK:
                # A locked screen with no explanation looks like a crash.
                tk.Label(
                    root, text=BANNER, bg="black", fg="#4a5568",
                    font=("Helvetica", 16),
                ).pack(expand=True)

            self._root = root
            self.screen_size = (screen_width, screen_height)

            # Wait for the window manager to actually map and size the window,
            # then confirm it covers the display. update_idletasks alone is not
            # enough: it does not process the map and configure events.
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                root.update()
                self.overlay_size = (root.winfo_width(), root.winfo_height())
                if self.overlay_covers_the_screen():
                    break
                time.sleep(0.05)

            if not self.overlay_covers_the_screen():
                # Last resort: bypass the window manager entirely.
                log.warning(
                    "the window manager left the overlay at %s; forcing it undecorated",
                    self.overlay_size,
                )
                root.overrideredirect(True)
                root.geometry(f"{screen_width}x{screen_height}+0+0")
                root.update()
                self.overlay_size = (root.winfo_width(), root.winfo_height())

            if not self.overlay_covers_the_screen():
                # Never claim the screen is blanked when it plainly is not.
                self._ready.put(
                    f"the overlay could not cover the screen "
                    f"({self.overlay_size} of {self.screen_size})"
                )
                return

            excluded = self._exclude_from_capture(root)
            if self.mode == MODE_EXCLUDED and not excluded:
                # Better to lock the screen than to believe the operator's work
                # is hidden when it is not.
                log.warning("capture-exclusion was refused; falling back to a guest lock")
                self.mode = MODE_GUEST_LOCK

            def poll() -> None:
                if self._stop.is_set():
                    root.quit()
                else:
                    root.after(100, poll)

            root.after(100, poll)
            self._ready.put(True)
            root.mainloop()
        except Exception as exc:
            if self._ready.empty():
                self._ready.put(str(exc))
            return
        finally:
            # The window must be destroyed by the thread that created it. Tcl
            # aborts the whole process if it is torn down anywhere else, and
            # dropping the last reference on another thread does exactly that.
            if root is not None:
                try:
                    root.quit()
                except Exception:
                    pass
                try:
                    root.destroy()
                except Exception:
                    pass
            self._root = None
            root = None

    def _exclude_from_capture(self, root) -> bool:
        """Ask the OS to keep this window out of screen captures."""
        if WINDOWS:
            return self._exclude_windows(root)
        if MACOS:
            return self._exclude_macos(root)
        return False

    def _exclude_windows(self, root) -> bool:
        """SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE).

        The window stays visible on the physical monitor and is dropped from
        anything that captures the screen, which is exactly the behaviour the
        privacy blank needs. Requires Windows 10 2004 or newer - the supported
        floor in the specification.
        """
        try:
            import ctypes

            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            handle = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            ok = ctypes.windll.user32.SetWindowDisplayAffinity(
                ctypes.c_void_p(handle), ctypes.c_uint(WDA_EXCLUDEFROMCAPTURE)
            )
            if not ok:
                log.warning(
                    "SetWindowDisplayAffinity failed (error %s)",
                    ctypes.windll.kernel32.GetLastError(),
                )
            return bool(ok)
        except Exception as exc:
            log.warning("could not exclude the overlay from capture: %s", exc)
            return False

    def _exclude_macos(self, root) -> bool:
        """NSWindowSharingNone keeps the window out of captures."""
        try:
            from AppKit import NSApp, NSWindowSharingNone

            root.update()
            windows = NSApp().windows() if NSApp() is not None else []
            if not windows:
                return False
            for window in windows:
                window.setSharingType_(NSWindowSharingNone)
            return True
        except Exception as exc:
            log.warning("could not set the window sharing type: %s", exc)
            return False

    # ---------------------------------------------------------- input block

    def _block_local_input(self) -> None:
        """Swallow input from the machine's own keyboard and mouse.

        Only used on the guest-lock path. On the capture-excluded path the
        operator is working behind the blank and local input must keep flowing,
        or their own injected events would be swallowed with it.
        """
        try:
            from pynput import keyboard, mouse

            key_listener = keyboard.Listener(
                on_press=lambda key: False, on_release=lambda key: False, suppress=True
            )
            mouse_listener = mouse.Listener(
                on_click=lambda *a: False, on_scroll=lambda *a: False, suppress=True
            )
            key_listener.start()
            mouse_listener.start()
            self._suppressors = [key_listener, mouse_listener]
            log.info("local input blocked")
        except Exception as exc:
            log.warning("could not block local input: %s", exc)
            self._suppressors = []

    def _release_local_input(self) -> None:
        for listener in self._suppressors:
            try:
                listener.stop()
            except Exception:
                pass
        self._suppressors = []

    # ------------------------------------------------------------ watchdog

    def _watchdog(self) -> None:
        deadline = time.monotonic() + self.watchdog_seconds
        while self.active and not self._stop.is_set():
            if time.monotonic() >= deadline:
                log.warning(
                    "privacy blank released by the watchdog after %.0fs",
                    self.watchdog_seconds,
                )
                self.disable()
                return
            time.sleep(0.25)

    def overlay_covers_the_screen(self) -> bool:
        """Whether the overlay really filled the display, measured inside the
        thread that owns it."""
        if not self.overlay_size or not self.screen_size:
            return False
        width, height = self.overlay_size
        screen_width, screen_height = self.screen_size
        return width >= screen_width - 2 and height >= screen_height - 2
