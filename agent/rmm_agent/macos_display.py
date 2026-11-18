"""macOS display state during a session (macOS only).

Two real-Mac problems a remote session hits, that do not exist on the test VM
but will on the boss's machines:

  * The display sleeps after the idle timeout. macOS stops compositing a slept
    display, so the operator's picture goes black mid-session for no obvious
    reason. Fix: hold a "no display sleep" power assertion for the life of the
    session with ``caffeinate -d`` (Apple's own tool; the documented, supported
    way), released the moment the session ends.

  * The user locks the Mac (or the screensaver with a password kicks in). The
    capture then shows the lock window, which reads as a black/blank picture.
    Fix: detect the lock with the public ``CGSessionCopyCurrentDictionary`` /
    ``CGSSessionScreenIsLocked`` and let the capture show a clear "screen is
    locked" message instead.

Both use the system tools/APIs through ctypes or a subprocess - nothing
bundled - and are no-ops off macOS, so Windows and Linux are unchanged.
"""
import logging
import platform
import subprocess

log = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"

LOCKED_TITLE = "This Mac's screen is locked"
LOCKED_STEPS = (
    "The person at this Mac has locked the screen, so nothing can be shown "
    "until they unlock it. Ask them to sign back in."
)

_CF_UTF8 = 0x08000100


def screen_locked() -> bool:
    """True if the Mac's screen is currently locked. False off macOS, and False
    if the state cannot be read - a failed check must never put up a false
    'locked' message over a working picture."""
    if not IS_MACOS:
        return False
    try:
        import ctypes
        import ctypes.util

        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        info = cg.CGSessionCopyCurrentDictionary()
        if not info:
            return False
        try:
            key = cf.CFStringCreateWithCString(None, b"CGSSessionScreenIsLocked", _CF_UTF8)
            try:
                value = cf.CFDictionaryGetValue(info, key)
                # The key is absent when unlocked; present and true when locked.
                return bool(value) and bool(cf.CFBooleanGetValue(value))
            finally:
                if key:
                    cf.CFRelease(key)
        finally:
            cf.CFRelease(info)
    except Exception as exc:  # pragma: no cover - never block the picture
        log.debug("could not read the macOS lock state: %s", exc)
        return False


class KeepDisplayAwake:
    """Holds a 'no display sleep' assertion for as long as it is active, so a
    session never goes black because the Mac's screen slept. No-op off macOS."""

    def __init__(self) -> None:
        self._proc = None

    def start(self) -> None:
        if not IS_MACOS or self._proc is not None:
            return
        try:
            # -d: prevent the display from sleeping. Runs until we kill it, so
            # the assertion lasts exactly as long as the session.
            self._proc = subprocess.Popen(
                ["/usr/bin/caffeinate", "-d"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("holding the display awake for this session (caffeinate -d)")
        except Exception as exc:
            log.debug("could not hold the display awake: %s", exc)
            self._proc = None

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception as exc:
            log.debug("could not release the display-awake assertion: %s", exc)
