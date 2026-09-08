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
                    (self._mouse.press if action == "down" else self._mouse.release)(button)
            elif kind == "scroll":
                steps = int(message.get("dy", 0) / 100) or (1 if message.get("dy", 0) < 0 else -1)
                self._mouse.scroll(0, -steps)
            elif kind == "key":
                name = message.get("key", "")
                target = self._special(name) or (name if len(name) == 1 else None)
                if target is None:
                    return
                if message.get("action") == "down":
                    self._keyboard.press(target)
                else:
                    self._keyboard.release(target)
        except Exception as exc:
            log.debug("could not apply input %s: %s", message, exc)
