"""Development guest: joins a session and streams this machine's screen.

This exists so the operator console's live behaviour - the connection
indicator, the LIVE preview, the viewer canvas, cursor mapping, fps/kbps and
input - can be exercised and tested for real on Linux today.

It is NOT the Phase 2 endpoint agent. It has no installer, no tray, no consent
surface and no unattended enrolment, and it has only been run on Linux.

    python agent/dev_guest.py --code ABCD1234
    python agent/dev_guest.py --code ABCD1234 --synthetic   # no display needed
"""
import argparse
import asyncio
import io
import json
import math
import os
import platform
import socket
import time

import websockets
from PIL import Image, ImageDraw

AGENT_VERSION = "0.1.0-dev"


def system_info() -> dict:
    info = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.release(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
        "cpu": platform.processor() or platform.machine(),
        "agent_version": AGENT_VERSION,
    }
    try:
        import psutil

        info["cores"] = psutil.cpu_count(logical=True)
        info["memory"] = f"{round(psutil.virtual_memory().total / 1024**3, 1)} GB"
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            info["ip"] = probe.getsockname()[0]
    except Exception:
        info["ip"] = "127.0.0.1"
    return info


class Capture:
    """Real screen capture, or a synthetic animation when there is no display."""

    def __init__(self, synthetic: bool, size: tuple[int, int] = (1280, 800)) -> None:
        self.synthetic = synthetic
        self.size = size
        self.monitor_index = 0
        self._sct = None
        self._monitors: list[dict] = []
        if not synthetic:
            import mss

            self._sct = mss.mss()
            # monitors[0] is the union of all screens; the real ones follow.
            for i, m in enumerate(self._sct.monitors[1:]):
                self._monitors.append(
                    {"index": i, "label": f"Monitor {i + 1}", "width": m["width"], "height": m["height"]}
                )
        if not self._monitors:
            self._monitors = [
                {"index": 0, "label": "Primary", "width": self.size[0], "height": self.size[1]}
            ]

    @property
    def monitors(self) -> list[dict]:
        return self._monitors

    def grab(self) -> Image.Image:
        if self.synthetic or self._sct is None:
            return self._synthetic_frame()
        monitor = self._sct.monitors[1:][self.monitor_index]
        shot = self._sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def _synthetic_frame(self) -> Image.Image:
        width, height = self.size
        image = Image.new("RGB", (width, height), (18, 30, 48))
        draw = ImageDraw.Draw(image)
        t = time.time()
        # A moving marker gives the viewer something unmistakably live, and the
        # corner labels make cursor-mapping errors obvious on screen.
        x = int((math.sin(t) * 0.5 + 0.5) * (width - 120)) + 60
        y = int((math.cos(t * 0.7) * 0.5 + 0.5) * (height - 120)) + 60
        draw.ellipse((x - 40, y - 40, x + 40, y + 40), fill=(47, 111, 228))
        draw.rectangle((0, 0, width - 1, height - 1), outline=(90, 120, 160), width=3)
        draw.text((20, 16), "SYNTHETIC GUEST SCREEN", fill=(220, 230, 245))
        draw.text((20, height - 30), "bottom-left", fill=(150, 175, 205))
        draw.text((width - 110, 16), "top-right", fill=(150, 175, 205))
        draw.text((20, 40), time.strftime("%H:%M:%S"), fill=(150, 175, 205))
        return image


class Input:
    """Applies operator input. Silently inert when no display backend loads."""

    def __init__(self, inject: bool = True) -> None:
        self.inject = inject
        self.mouse = None
        self.keyboard = None
        if not inject:
            # Echo-only: used by the automated tests so a test run never takes
            # over the real mouse and keyboard of the machine it runs on.
            return
        try:
            from pynput.keyboard import Controller as KeyboardController
            from pynput.mouse import Controller as MouseController

            self.mouse = MouseController()
            self.keyboard = KeyboardController()
        except Exception:
            pass

    def apply(self, message: dict, frame_size: tuple[int, int]) -> None:
        if not self.inject:
            if message.get("kind") == "mouse":
                print(
                    f"input mouse {message.get('action')} "
                    f"x={message.get('x', -1):.4f} y={message.get('y', -1):.4f} "
                    f"px={int(message.get('x', 0) * frame_size[0])} "
                    f"py={int(message.get('y', 0) * frame_size[1])}",
                    flush=True,
                )
            elif message.get("kind") == "key":
                print(f"input key {message.get('action')} {message.get('key')!r}", flush=True)
            return
        if self.mouse is None:
            return
        from pynput.mouse import Button

        kind = message.get("kind")
        width, height = frame_size
        if kind == "mouse":
            if "x" in message and "y" in message:
                self.mouse.position = (int(message["x"] * width), int(message["y"] * height))
            action = message.get("action")
            if action in ("down", "up"):
                button = {"left": Button.left, "right": Button.right, "middle": Button.middle}[
                    message.get("button", "left")
                ]
                (self.mouse.press if action == "down" else self.mouse.release)(button)
        elif kind == "scroll":
            self.mouse.scroll(0, -int(message.get("dy", 0)) // 100 or 0)
        elif kind == "key" and self.keyboard is not None:
            from pynput.keyboard import Key

            key = message.get("key", "")
            special = {
                "Enter": Key.enter, "Backspace": Key.backspace, "Tab": Key.tab,
                "Escape": Key.esc, "ArrowUp": Key.up, "ArrowDown": Key.down,
                "ArrowLeft": Key.left, "ArrowRight": Key.right, "Shift": Key.shift,
                "Control": Key.ctrl, "Alt": Key.alt, "Meta": Key.cmd, " ": Key.space,
            }.get(key)
            target = special if special is not None else (key if len(key) == 1 else None)
            if target is None:
                return
            if message.get("action") == "down":
                self.keyboard.press(target)
            else:
                self.keyboard.release(target)


async def run(
    url: str, code: str, fps: int, quality: int, synthetic: bool, inject: bool
) -> None:
    capture = Capture(synthetic)
    injector = Input(inject=inject)
    endpoint = f"{url.rstrip('/')}/ws/guest/{code.upper()}"
    print(f"connecting to {endpoint}", flush=True)

    async with websockets.connect(endpoint, max_size=None) as socket_:
        info = system_info()
        await socket_.send(
            json.dumps(
                {
                    "host_name": info["hostname"],
                    "system_info": info,
                    "monitors": capture.monitors,
                }
            )
        )
        print(f"joined session {code.upper()} as {info['hostname']}", flush=True)

        blanked = False
        frame_size = (0, 0)
        interval = 1 / fps

        async def receive() -> None:
            nonlocal blanked
            async for raw in socket_:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = message.get("type")
                if kind == "input":
                    injector.apply(message, frame_size)
                elif kind == "monitor":
                    index = int(message.get("index", 0))
                    if 0 <= index < len(capture.monitors):
                        capture.monitor_index = index
                        print(f"switched to monitor {index}", flush=True)
                elif kind == "blank":
                    blanked = bool(message.get("on"))
                    print(f"privacy blank {'on' if blanked else 'off'}", flush=True)

        receiver = asyncio.create_task(receive())
        try:
            while True:
                started = time.perf_counter()
                image = capture.grab()
                frame_size = image.size
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality)
                await socket_.send(buffer.getvalue())
                elapsed = time.perf_counter() - started
                await asyncio.sleep(max(0.0, interval - elapsed))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            receiver.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://localhost:8000", help="relay WebSocket base URL")
    parser.add_argument("--code", required=True, help="the session join code")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--quality", type=int, default=60, help="JPEG quality, 1-95")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="stream a generated test image instead of the real screen",
    )
    parser.add_argument(
        "--no-input",
        dest="inject",
        action="store_false",
        help="log operator input instead of injecting it (used by the tests)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(
            run(args.url, args.code, args.fps, args.quality, args.synthetic, args.inject)
        )
    except KeyboardInterrupt:
        print("\nleft the session")


if __name__ == "__main__":
    main()
