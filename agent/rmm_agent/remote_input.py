"""Applies operator input to this machine.

pynput is used on every platform; on Windows it drives SendInput, on macOS
CGEvent and on Linux XTest, which is exactly the mapping in the specification's
per-platform table.
"""
import logging

log = logging.getLogger(__name__)


class InputInjector:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.available = False
        self._mouse = None
        self._keyboard = None
        self._Button = None
        self._Key = None
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
                dy = message.get("dy", 0)
                # A small nonzero delta still rounds to int(dy/100) == 0, and
                # that case is meant to fall through to a minimum one-notch
                # scroll in the right direction - but int(0/100) is also 0,
                # so a *zero*-delta event used to hit that same fallback and
                # produce an unasked-for one-notch scroll on every such event.
                if dy == 0:
                    steps = 0
                else:
                    steps = int(dy / 100) or (1 if dy < 0 else -1)
                if steps:
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
                    self._keyboard.release(target)
                    self._pressed_keys.discard(target)
        except Exception as exc:
            log.debug("could not apply input %s: %s", message, exc)

    def release_all(self) -> None:
        """Let go of everything still held down.

        Call this whenever a session ends for any reason - a clean end, a
        dropped connection, anything. Without it, a connection that dropped
        between a down and its matching up (mid-drag, mid-shortcut) left that
        button or key physically stuck at the OS level with no way to clear
        it, even across a reconnect.
        """
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
