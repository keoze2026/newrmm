"""macOS screen-recording and accessibility permission detection (macOS only).

Why this exists (proven on a real Mac, 2026-11-17): macOS withholds the screen
from any app that does not hold **Screen Recording** permission. The app is not
told "denied" - the capture simply comes back as a flat redacted fill (a solid
grey), so the operator sees a blank picture while frames keep flowing. Our
builds are ad-hoc signed, and macOS keys the permission to the code signature,
so every rebuilt/updated agent is a "new" app that has lost the grant. The same
is true of **Accessibility**, without which injected mouse/keyboard events do
nothing.

So instead of silently streaming grey, the agent must DETECT the missing
permission and say exactly what to turn on. The checks use the public Apple C
APIs through ctypes against the system frameworks - never a bundled pyobjc
module - so they need nothing packaged and behave the same on every macOS
release (the same approach remote_input.py already uses for the Accessibility
prompt):

  * ``CGPreflightScreenCaptureAccess``  (CoreGraphics, macOS 10.15+)
  * ``CGRequestScreenCaptureAccess``    (CoreGraphics, macOS 10.15+)
  * ``AXIsProcessTrusted``              (ApplicationServices)

Everything here is a no-op off macOS: the "granted" checks return True so Linux
and Windows behaviour is completely unchanged.
"""
import logging
import platform

log = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"

# What the endpoint user has to do, in plain words. Shown to them (notification)
# and drawn onto the operator's picture so the operator can read it out.
SCREEN_RECORDING_TITLE = "Screen Recording permission needed"
SCREEN_RECORDING_STEPS = (
    "This Mac is not sharing its screen yet. Open System Settings > "
    "Privacy & Security > Screen Recording, switch on “rmm-agent”, "
    "then quit and reopen the app."
)
ACCESSIBILITY_TITLE = "Accessibility permission needed"
ACCESSIBILITY_STEPS = (
    "The operator cannot control this Mac yet. Open System Settings > "
    "Privacy & Security > Accessibility, switch on “rmm-agent”."
)


def _coregraphics():
    import ctypes
    import ctypes.util

    return ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))


def _application_services():
    import ctypes
    import ctypes.util

    return ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))


def screen_recording_granted() -> bool:
    """True if this process may capture the screen.

    True off macOS (nothing to grant) and True if the check cannot be made, so a
    failure here never blocks capture on any platform - it only ever adds the
    explanatory frame when we are certain the permission is missing.
    """
    if not IS_MACOS:
        return True
    try:
        import ctypes

        cg = _coregraphics()
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        cg.CGPreflightScreenCaptureAccess.argtypes = []
        return bool(cg.CGPreflightScreenCaptureAccess())
    except Exception as exc:  # pragma: no cover - never block capture
        log.debug("could not check Screen Recording permission: %s", exc)
        return True


def request_screen_recording() -> bool:
    """Register this app for Screen Recording and show the system prompt.

    Like the Accessibility request, this is what puts the app into the System
    Settings list so the user has something to switch on; it is a no-op once
    granted. Returns whether permission is held after asking.
    """
    if not IS_MACOS:
        return True
    try:
        import ctypes

        cg = _coregraphics()
        cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        cg.CGRequestScreenCaptureAccess.argtypes = []
        granted = bool(cg.CGRequestScreenCaptureAccess())
        log.info("requested macOS Screen Recording (granted: %s)", granted)
        return granted
    except Exception as exc:  # pragma: no cover - never block capture
        log.debug("could not request Screen Recording permission: %s", exc)
        return False


def accessibility_granted() -> bool:
    """True if injected input will actually reach the Mac. True off macOS."""
    if not IS_MACOS:
        return True
    try:
        import ctypes

        ax = _application_services()
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        ax.AXIsProcessTrusted.argtypes = []
        return bool(ax.AXIsProcessTrusted())
    except Exception as exc:  # pragma: no cover - never block input
        log.debug("could not check Accessibility permission: %s", exc)
        return True


def render_permission_frame(size, lines):
    """A readable picture that explains the missing permission, so the operator
    sees the reason instead of a silent grey screen. ``lines`` is a list of
    strings; the first is drawn as a heading."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = size

    def _font(px):
        # Scale PIL's built-in font so the message is readable once the operator's
        # viewer shrinks a 1920-wide frame. load_default(size=) needs Pillow
        # 10.1+; fall back to the fixed-size default on anything older. No font
        # file is ever loaded, so nothing has to be bundled.
        try:
            return ImageFont.load_default(size=px)
        except TypeError:
            return ImageFont.load_default()

    heading_px = max(22, width // 46)
    body_px = max(16, width // 70)
    image = Image.new("RGB", (width, height), (24, 26, 33))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(214, 69, 69), width=max(4, width // 320))
    margin = max(60, width // 20)
    avail = width - 2 * margin

    def _wrap(text, font):
        words, out, line = text.split(), [], ""
        for w in words:
            trial = (line + " " + w).strip()
            if draw.textlength(trial, font=font) <= avail or not line:
                line = trial
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
        return out

    # Lay the (wrapped) lines out and centre the block vertically.
    rows = []
    for i, text in enumerate(lines):
        font = _font(heading_px if i == 0 else body_px)
        step = int(heading_px * 1.5) if i == 0 else int(body_px * 1.6)
        colour = (245, 246, 250) if i == 0 else (180, 188, 200)
        for wrapped in _wrap(text, font):
            rows.append((wrapped, font, colour, step))
        if i == 0:
            rows.append(("", font, colour, int(heading_px * 0.6)))  # gap after heading
    total = sum(step for _, _, _, step in rows)
    y = max(40, (height - total) // 2)
    for text, font, colour, step in rows:
        if text:
            draw.text((margin, y), text, fill=colour, font=font)
        y += step
    return image
