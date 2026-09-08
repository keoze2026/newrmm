"""Screen capture.

Phase 2 uses mss on every platform, which is enough to stream a live screen and
be controlled. The native Windows.Graphics.Capture engine (Rust) arrives in
Phase 5, where the privacy blank needs capture-exclusion.
"""
import io
import logging
import math
import time

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)


class ScreenCapture:
    def __init__(self, synthetic: bool = False, size: tuple[int, int] = (1280, 800)) -> None:
        self.synthetic = synthetic
        self.size = size
        self.monitor_index = 0
        self._sct = None
        self._monitors: list[dict] = []

        if not synthetic:
            try:
                import mss

                self._sct = mss.mss()
                for i, m in enumerate(self._sct.monitors[1:]):
                    self._monitors.append(
                        {
                            "index": i,
                            "label": f"Monitor {i + 1}",
                            "width": m["width"],
                            "height": m["height"],
                        }
                    )
            except Exception as exc:
                log.warning("screen capture unavailable (%s); using a generated image", exc)
                self.synthetic = True

        if not self._monitors:
            self._monitors = [
                {"index": 0, "label": "Primary", "width": self.size[0], "height": self.size[1]}
            ]

    @property
    def monitors(self) -> list[dict]:
        return self._monitors

    def select(self, index: int) -> bool:
        if 0 <= index < len(self._monitors):
            self.monitor_index = index
            log.info("capturing monitor %s", index)
            return True
        return False

    def grab(self) -> Image.Image:
        if self.synthetic or self._sct is None:
            return self._generated()
        monitor = self._sct.monitors[1:][self.monitor_index]
        shot = self._sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def encode(self, image: Image.Image, quality: int) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()

    def _generated(self) -> Image.Image:
        width, height = self.size
        image = Image.new("RGB", (width, height), (18, 30, 48))
        draw = ImageDraw.Draw(image)
        t = time.time()
        x = int((math.sin(t) * 0.5 + 0.5) * (width - 120)) + 60
        y = int((math.cos(t * 0.7) * 0.5 + 0.5) * (height - 120)) + 60
        draw.ellipse((x - 40, y - 40, x + 40, y + 40), fill=(47, 111, 228))
        draw.rectangle((0, 0, width - 1, height - 1), outline=(90, 120, 160), width=3)
        draw.text((20, 16), "SYNTHETIC GUEST SCREEN", fill=(220, 230, 245))
        draw.text((20, 40), time.strftime("%H:%M:%S"), fill=(150, 175, 205))
        draw.text((20, height - 30), "bottom-left", fill=(150, 175, 205))
        draw.text((width - 110, 16), "top-right", fill=(150, 175, 205))
        return image


class RateController:
    """Keeps the stream usable on a constrained link (spec section 8: usable at
    about 1 Mbps) by trading quality and frame rate against measured bandwidth."""

    def __init__(self, target_fps: int, quality: int) -> None:
        self.target_fps = target_fps
        self.base_quality = quality
        self.quality = quality
        self.fps = target_fps
        self._sent: list[tuple[float, int]] = []

    def record(self, size: int) -> None:
        now = time.monotonic()
        self._sent.append((now, size))
        self._sent = [(t, s) for t, s in self._sent if now - t <= 2.0]

    @property
    def kbps(self) -> int:
        if len(self._sent) < 2:
            return 0
        span = max(0.5, self._sent[-1][0] - self._sent[0][0])
        return int(sum(s for _, s in self._sent) * 8 / span / 1000)

    def adjust(self, budget_kbps: int) -> None:
        """Nudge quality and frame rate toward the bandwidth budget."""
        if budget_kbps <= 0:
            return
        measured = self.kbps
        if measured > budget_kbps * 1.15:
            self.quality = max(30, self.quality - 5)
            if self.quality <= 35:
                self.fps = max(4, self.fps - 1)
        elif measured < budget_kbps * 0.7:
            self.quality = min(self.base_quality, self.quality + 3)
            if self.quality >= self.base_quality:
                self.fps = min(self.target_fps, self.fps + 1)

    @property
    def interval(self) -> float:
        return 1.0 / max(1, self.fps)
