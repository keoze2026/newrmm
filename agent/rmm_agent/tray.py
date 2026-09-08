"""Tray presence indicator and session notifications (spec section 9)."""
import logging
import threading

log = logging.getLogger(__name__)

IDLE = "idle"
CONNECTED = "connected"
SHARING = "sharing"

_COLOURS = {
    IDLE: (107, 122, 144),
    CONNECTED: (47, 111, 228),
    SHARING: (31, 170, 90),
}


def _icon_image(state: str):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=_COLOURS.get(state, _COLOURS[IDLE]))
    draw.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 235))
    return image


class Tray:
    """Wraps pystray so the agent still runs when no tray is available."""

    def __init__(self, on_quit) -> None:
        self.on_quit = on_quit
        self.available = False
        self._icon = None
        self._state = IDLE
        self._status = "Not in a session"
        try:
            import pystray

            self._pystray = pystray
            self._icon = pystray.Icon(
                "rmm-agent",
                _icon_image(IDLE),
                "Remote support agent",
                menu=pystray.Menu(
                    pystray.MenuItem(lambda item: self._status, lambda: None, enabled=False),
                    pystray.MenuItem("End session and quit", self._quit),
                ),
            )
            self.available = True
        except Exception as exc:
            log.warning("tray unavailable: %s", exc)

    def _quit(self, *_args) -> None:
        log.info("quit requested from the tray")
        try:
            self.on_quit()
        finally:
            self.stop()

    def set_state(self, state: str, status: str) -> None:
        self._state = state
        self._status = status
        if self._icon is not None:
            try:
                self._icon.icon = _icon_image(state)
                self._icon.title = f"Remote support agent — {status}"
                self._icon.update_menu()
            except Exception as exc:
                log.debug("could not update the tray: %s", exc)
        log.info("presence: %s (%s)", state, status)

    def notify(self, message: str, title: str = "Remote support") -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
                return
            except Exception as exc:
                log.debug("tray notification failed: %s", exc)
        log.info("notification: %s — %s", title, message)

    def run(self) -> None:
        """Blocks. The tray owns the main thread where one exists."""
        if self._icon is None:
            threading.Event().wait()
            return
        self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
