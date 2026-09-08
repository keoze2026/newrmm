"""Per-OS setup and capability checks.

Windows needs DPI awareness before anything is captured, or a scaled display is
captured at the wrong resolution and clicks land in the wrong place. macOS needs
two separate permissions - Screen Recording to capture, Accessibility to inject
input - and silently does nothing when they are missing, so they are checked and
reported rather than left to fail mysteriously.
"""
import logging
import os
import platform

log = logging.getLogger(__name__)

WINDOWS = platform.system() == "Windows"
MACOS = platform.system() == "Darwin"
LINUX = platform.system() == "Linux"


def prepare() -> None:
    """Run once at startup, before capture or input."""
    if WINDOWS:
        _make_dpi_aware()


def _make_dpi_aware() -> None:
    """Tell Windows this process handles its own scaling.

    Without it, a display at 150% scaling is captured at the smaller logical
    size and every injected click is offset.
    """
    try:
        import ctypes

        # PER_MONITOR_AWARE_V2; falls back for Windows 8.1 and older.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            log.debug("DPI awareness: per-monitor v2")
            return
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            log.debug("DPI awareness: per-monitor")
            return
        except (AttributeError, OSError):
            pass
        ctypes.windll.user32.SetProcessDPIAware()
        log.debug("DPI awareness: system")
    except Exception as exc:
        log.warning("could not set DPI awareness: %s", exc)


def screen_recording_permission() -> bool | None:
    """macOS only. True/False when known, None where it does not apply."""
    if not MACOS:
        return None
    try:
        import ctypes
        import ctypes.util

        core_graphics = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("CoreGraphics") or "CoreGraphics"
        )
        # Present from macOS 10.15, which is below the supported floor of 12.
        preflight = getattr(core_graphics, "CGPreflightScreenCaptureAccess", None)
        if preflight is None:
            return None
        preflight.restype = ctypes.c_bool
        return bool(preflight())
    except Exception as exc:
        log.debug("could not check screen recording permission: %s", exc)
        return None


def request_screen_recording_permission() -> None:
    """macOS only. Triggers the system prompt the first time it is called."""
    if not MACOS:
        return
    try:
        import ctypes
        import ctypes.util

        core_graphics = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("CoreGraphics") or "CoreGraphics"
        )
        request = getattr(core_graphics, "CGRequestScreenCaptureAccess", None)
        if request is not None:
            request.restype = ctypes.c_bool
            request()
    except Exception as exc:
        log.debug("could not request screen recording permission: %s", exc)


def accessibility_permission() -> bool | None:
    """macOS only: needed before injected input does anything at all."""
    if not MACOS:
        return None
    try:
        import ctypes
        import ctypes.util

        app_services = ctypes.cdll.LoadLibrary(
            ctypes.util.find_library("ApplicationServices") or "ApplicationServices"
        )
        trusted = getattr(app_services, "AXIsProcessTrusted", None)
        if trusted is None:
            return None
        trusted.restype = ctypes.c_bool
        return bool(trusted())
    except Exception as exc:
        log.debug("could not check accessibility permission: %s", exc)
        return None


def session_type() -> str:
    """Linux only: X11 or Wayland, which decide what capture can do."""
    if not LINUX:
        return platform.system()
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


def warnings() -> list[str]:
    """Human-readable problems worth telling the operator about."""
    notes: list[str] = []

    if MACOS:
        if screen_recording_permission() is False:
            notes.append(
                "Screen Recording permission is not granted. Allow it in System "
                "Settings > Privacy & Security > Screen Recording, then restart "
                "the agent - macOS only applies it on relaunch."
            )
        if accessibility_permission() is False:
            notes.append(
                "Accessibility permission is not granted, so keyboard and mouse "
                "control will do nothing. Allow it in System Settings > Privacy "
                "& Security > Accessibility."
            )
    elif LINUX:
        kind = session_type()
        if kind == "wayland":
            notes.append(
                "This is a Wayland session. Screen capture goes through the "
                "XDG portal and input injection through XTest may be refused; "
                "an Xorg session is the reliable option until the PipeWire "
                "capture path lands."
            )
        elif kind == "headless":
            notes.append("No display was found; capture will be a generated image.")

    return notes
