"""Applies operator input to this machine.

pynput is used on Windows (SendInput), macOS (CGEvent) and X11/XWayland Linux
(XTest), exactly the mapping in the specification's per-platform table. A
native Wayland session has no XTest - that is blocked by design, the same
reason X11 capture does not work there either - so on Wayland this instead
drives the already-started xdg-desktop-portal RemoteDesktop session
(wayland_portal.PortalSession) that session.py shares with ScreenCapture.
"""
import logging

from rmm_agent import wayland_portal

log = logging.getLogger(__name__)


def scroll_steps(dy) -> int:
    """Browser deltaY -> whole wheel notches; positive means down.

    About 100 is one notch. A smaller delta (trackpads, line-mode wheels
    sending 3) still scrolls one notch, in its own direction - it used to go
    the opposite way. Zero scrolls nothing."""
    try:
        dy = float(dy)
    except (TypeError, ValueError):
        return 0
    if dy == 0:
        return 0
    return int(dy / 100) or (1 if dy > 0 else -1)


def _held_variant(target, pressed: set):
    """The key actually held for a release. Press "a", then Shift, then let
    go of the letter: the browser reports "A", and releasing "A" left "a"
    held down. Case is matched for letters and their keysyms."""
    if target in pressed:
        return target
    if isinstance(target, str) and len(target) == 1:
        for held in pressed:
            if isinstance(held, str) and held.lower() == target.lower():
                return held
    if isinstance(target, int) and target < 0x100:
        for held in pressed:
            if isinstance(held, int) and held < 0x100 and chr(held).lower() == chr(target).lower():
                return held
    return target


class InputInjector:
    def __init__(self, enabled: bool = True, portal=None) -> None:
        """`portal`: an already-started wayland_portal.PortalSession, shared
        with ScreenCapture, when session.py detected a Wayland session."""
        self.enabled = enabled
        self.available = False
        self._mouse = None
        self._keyboard = None
        self._Button = None
        self._Key = None
        self._portal = None
        # What this operator is currently holding down. Nothing else records
        # this: if the connection drops between a down and its matching up -
        # mid-drag, or mid-shortcut - the button/key stayed physically pressed
        # at the OS level forever, with no code path that ever released it,
        # not even on the next reconnect.
        self._pressed_buttons: set = set()
        self._pressed_keys: set = set()
        if not enabled:
            log.info("input injection disabled; operator input will only be logged")
            return

        if portal is not None and getattr(portal, "input_available", False):
            self._portal = portal
            self.available = True
            log.info("input injection via the Wayland portal (RemoteDesktop)")
            return

        try:
            from pynput.keyboard import Controller as KeyboardController, Key
            from pynput.mouse import Button, Controller as MouseController

            self._mouse = MouseController()
            self._keyboard = KeyboardController()
            self._Button = Button
            self._Key = Key
            self.available = True
        except Exception as exc:
            log.warning("input injection unavailable: %s", exc)

    # Browser key names -> pynput keys.
    def _special(self, name: str):
        Key = self._Key
        return {
            "Enter": Key.enter, "Backspace": Key.backspace, "Tab": Key.tab,
            "Escape": Key.esc, "Delete": Key.delete, "Home": Key.home, "End": Key.end,
            "PageUp": Key.page_up, "PageDown": Key.page_down,
            "ArrowUp": Key.up, "ArrowDown": Key.down,
            "ArrowLeft": Key.left, "ArrowRight": Key.right,
            "Shift": Key.shift, "Control": Key.ctrl, "Alt": Key.alt,
            "Meta": Key.cmd, "CapsLock": Key.caps_lock, " ": Key.space,
            "F1": Key.f1, "F2": Key.f2, "F3": Key.f3, "F4": Key.f4,
            "F5": Key.f5, "F6": Key.f6, "F7": Key.f7, "F8": Key.f8,
            "F9": Key.f9, "F10": Key.f10, "F11": Key.f11, "F12": Key.f12,
        }.get(name)

    def apply(self, message: dict, geometry: tuple[int, int, int, int]) -> None:
        """`geometry` is (left, top, width, height) of the captured display in
        the OS's own coordinate space, so a click maps correctly on a scaled or
        secondary monitor."""
        kind = message.get("kind")
        if not self.available:
            # Echo mode is deliberate diagnostic output - either injection is
            # unavailable, or --no-input asked for it - so log it at info level
            # rather than hiding it behind --verbose.
            if kind == "mouse":
                log.info(
                    "input mouse %s x=%.4f y=%.4f",
                    message.get("action"), message.get("x", -1), message.get("y", -1),
                )
            elif kind == "key":
                log.info("input key %s %r", message.get("action"), message.get("key"))
            return

        if self._portal is not None:
            self._apply_portal(message, geometry)
            return

        left, top, width, height = geometry
        try:
            if kind == "mouse":
                if "x" in message and "y" in message and width and height:
                    # Coordinates arrive normalised, so letterboxing in the
                    # operator's viewer cannot shift where the click lands.
                    self._mouse.position = (
                        left + int(message["x"] * width),
                        top + int(message["y"] * height),
                    )
                action = message.get("action")
                if action in ("down", "up"):
                    button = {
                        "left": self._Button.left,
                        "right": self._Button.right,
                        "middle": self._Button.middle,
                    }.get(message.get("button", "left"), self._Button.left)
                    if action == "down":
                        self._mouse.press(button)
                        self._pressed_buttons.add(button)
                    else:
                        self._mouse.release(button)
                        self._pressed_buttons.discard(button)
            elif kind == "scroll":
                steps = scroll_steps(message.get("dy", 0))
                if steps:
                    # pynput: positive scrolls up, so a downward step is negative.
                    self._mouse.scroll(0, -steps)
            elif kind == "key":
                name = message.get("key", "")
                target = self._special(name) or (name if len(name) == 1 else None)
                if target is None:
                    return
                if message.get("action") == "down":
                    self._keyboard.press(target)
                    self._pressed_keys.add(target)
                else:
                    target = _held_variant(target, self._pressed_keys)
                    self._keyboard.release(target)
                    self._pressed_keys.discard(target)
        except Exception as exc:
            log.debug("could not apply input %s: %s", message, exc)

    def _apply_portal(self, message: dict, geometry: tuple[int, int, int, int]) -> None:
        """Same semantics as the pynput path above, driving the Wayland
        portal's RemoteDesktop Notify* calls instead of XTest."""
        left, top, width, height = geometry
        kind = message.get("kind")
        try:
            if kind == "mouse":
                if "x" in message and "y" in message and width and height:
                    # The portal's absolute motion is in the shared stream's
                    # own space (0..width), not desktop coordinates - adding
                    # the monitor's left/top pushed every move off a monitor
                    # that is not at the origin.
                    x = min(max(float(message["x"]), 0.0), 1.0)
                    y = min(max(float(message["y"]), 0.0), 1.0)
                    self._portal.notify_pointer_motion_absolute(x * width, y * height)
                action = message.get("action")
                if action in ("down", "up"):
                    button = {
                        "left": wayland_portal.BTN_LEFT,
                        "right": wayland_portal.BTN_RIGHT,
                        "middle": wayland_portal.BTN_MIDDLE,
                    }.get(message.get("button", "left"), wayland_portal.BTN_LEFT)
                    pressed = action == "down"
                    self._portal.notify_pointer_button(button, pressed)
                    if pressed:
                        self._pressed_buttons.add(button)
                    else:
                        self._pressed_buttons.discard(button)
            elif kind == "scroll":
                steps = scroll_steps(message.get("dy", 0))
                if steps:
                    # Wayland's axis: positive scrolls down, like the browser.
                    self._portal.notify_pointer_axis_discrete(True, steps)
            elif kind == "key":
                name = message.get("key", "")
                keysym = wayland_portal.keysym_for(name)
                if keysym is None:
                    return
                pressed = message.get("action") == "down"
                if not pressed:
                    keysym = _held_variant(keysym, self._pressed_keys)
                self._portal.notify_keyboard_keysym(keysym, pressed)
                if pressed:
                    self._pressed_keys.add(keysym)
                else:
                    self._pressed_keys.discard(keysym)
        except Exception as exc:
            log.debug("could not apply portal input %s: %s", message, exc)

    def release_all(self) -> None:
        """Let go of everything still held down.

        Call this whenever a session ends for any reason - a clean end, a
        dropped connection, anything. Without it, a connection that dropped
        between a down and its matching up (mid-drag, mid-shortcut) left that
        button or key physically stuck at the OS level with no way to clear
        it, even across a reconnect.
        """
        if self._portal is not None:
            for button in list(self._pressed_buttons):
                self._portal.notify_pointer_button(button, False)
            for keysym in list(self._pressed_keys):
                self._portal.notify_keyboard_keysym(keysym, False)
            self._pressed_buttons.clear()
            self._pressed_keys.clear()
            return
        if not self.available:
            self._pressed_buttons.clear()
            self._pressed_keys.clear()
            return
        for button in list(self._pressed_buttons):
            try:
                self._mouse.release(button)
            except Exception as exc:
                log.debug("could not release mouse button %s: %s", button, exc)
        for key in list(self._pressed_keys):
            try:
                self._keyboard.release(key)
            except Exception as exc:
                log.debug("could not release key %s: %s", key, exc)
        self._pressed_buttons.clear()
        self._pressed_keys.clear()
