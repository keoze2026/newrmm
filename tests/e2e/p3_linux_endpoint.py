"""Phase 3, Linux half: real screen capture and real input injection.

Verifies the endpoint agent on this machine for real - not the synthetic test
image and not a logging stub:

  * the native C capture module (X11 XShm) captures the actual desktop
  * pynput actually injects mouse and keyboard events through XTest, confirmed
    by a listener that receives them
  * the tray backend loads

The pointer is moved during the input check and put back where it was, and the
key injected is a modifier that types nothing.

    python tests/e2e/p3_linux_endpoint.py
"""
import platform
import sys
import time

sys.path.insert(0, "agent")

results: list[tuple[bool, str]] = []


def step(name, fn):
    try:
        fn()
        results.append((True, name))
        print(f"PASS  {name}")
    except Exception as exc:
        results.append((False, name))
        print(f"FAIL  {name}\n      {exc}")


def main() -> int:
    from rmm_agent import sysinfo
    from rmm_agent.capture import RateController, ScreenCapture
    from rmm_agent.remote_input import InputInjector
    from rmm_agent.tray import Tray

    print(f"platform: {sysinfo.platform_key()} ({platform.platform()})\n")

    capture = ScreenCapture()

    def native_module_in_use():
        """The specification requires a native capture module per OS, not the
        pure-Python fallback."""
        assert capture.backend.startswith("native-"), (
            f"the native module is not in use (backend={capture.backend!r}). "
            "Build it with: python agent/native/linux/setup.py build_ext --inplace"
        )
        print(f"      capture backend: {capture.backend}")

    step("the native C capture module is in use, not the mss fallback",
         native_module_in_use)

    def real_capture():
        assert not capture.synthetic, "capture did not attach to a display"
        assert capture.monitors, "no monitors enumerated"
        for m in capture.monitors:
            assert m["width"] > 0 and m["height"] > 0, m

    step("the native module enumerates the real displays", real_capture)

    frames = {}

    def grabs_desktop():
        image = capture.grab()
        assert image.width > 200 and image.height > 200, image.size
        # A real desktop is not a single flat colour.
        colours = image.resize((64, 64)).getcolors(maxcolors=64 * 64)
        assert colours is not None and len(colours) > 8, f"only {colours and len(colours)} colours"
        frames["size"] = image.size
        frames["image"] = image

    step("a frame of the real desktop is captured", grabs_desktop)

    def encodes():
        payload = capture.encode(frames["image"], 60)
        assert payload.startswith(b"\xff\xd8"), "not a JPEG"
        assert 3_000 < len(payload) < 4_000_000, len(payload)
        frames["bytes"] = len(payload)

    step("the frame encodes to a sane JPEG", encodes)

    def sustains_rate():
        rate = RateController(target_fps=12, quality=60)
        started = time.perf_counter()
        count = 0
        while time.perf_counter() - started < 2.0:
            payload = capture.encode(capture.grab(), rate.quality)
            rate.record(len(payload))
            count += 1
        fps = count / (time.perf_counter() - started)
        print(f"      captured {fps:.1f} fps at {frames['bytes'] // 1024} KB/frame, {rate.kbps} kbps")
        assert fps >= 5, f"only {fps:.1f} fps"

    step("capture sustains at least 5 fps on the real desktop", sustains_rate)

    def adapts():
        rate = RateController(target_fps=12, quality=60)
        for _ in range(30):
            rate.record(200_000)  # far above any sane budget
        rate.adjust(budget_kbps=1000)
        assert rate.quality < 60, "quality did not drop under a tight budget"
        lean = RateController(target_fps=12, quality=60)
        lean.quality = 40
        for _ in range(5):
            lean.record(500)
        lean.adjust(budget_kbps=1000)
        assert lean.quality > 40, "quality did not recover on a fast link"

    step("the rate controller adapts quality to the bandwidth budget", adapts)

    injector = InputInjector()

    def input_available():
        assert injector.available, "pynput did not load an input backend"

    step("pynput input backend loads", input_available)

    def mouse_really_moves():
        """Inject a move and read the pointer back, then restore it."""
        from pynput.mouse import Controller

        mouse = Controller()
        original = mouse.position
        geometry = capture.geometry
        left, top, width, height = geometry
        try:
            injector.apply(
                {"kind": "mouse", "action": "move", "x": 0.25, "y": 0.75}, geometry
            )
            time.sleep(0.25)
            x, y = mouse.position
            expected = (left + int(0.25 * width), top + int(0.75 * height))
            assert abs(x - expected[0]) <= 4 and abs(y - expected[1]) <= 4, (
                f"asked for {expected}, pointer went to {(x, y)}"
            )
        finally:
            mouse.position = original

    step("a normalised move lands on the right pixel of the real screen", mouse_really_moves)

    def keyboard_events_are_delivered():
        """Inject a modifier and confirm a listener receives it."""
        from pynput import keyboard

        seen = []
        listener = keyboard.Listener(on_press=lambda key: seen.append(key))
        listener.start()
        time.sleep(0.4)
        try:
            injector.apply({"kind": "key", "action": "down", "key": "Shift"}, capture.geometry)
            time.sleep(0.4)
        finally:
            injector.apply({"kind": "key", "action": "up", "key": "Shift"}, capture.geometry)
            time.sleep(0.2)
            listener.stop()
        assert seen, "the injected keystroke was never delivered"
        assert any("shift" in str(k).lower() for k in seen), f"got {seen}"

    step("an injected keystroke is actually delivered to X", keyboard_events_are_delivered)

    def geometry_matches_the_display():
        left, top, width, height = capture.geometry
        assert width > 0 and height > 0, capture.geometry
        pixels = frames["size"]
        # On this X11 machine there is no Retina doubling, so the captured
        # pixels and the logical geometry should agree.
        assert pixels == (width, height), f"captured {pixels}, geometry says {(width, height)}"
        print(f"      geometry {width}x{height} at {left},{top}")

    step("the reported geometry matches the captured frame", geometry_matches_the_display)

    def monitor_switch():
        assert capture.select(0) is True
        assert capture.select(99) is False, "an out-of-range monitor was accepted"

    step("monitor selection accepts real indices and rejects bad ones", monitor_switch)

    def tray_backend():
        assert Tray(lambda: None).available, "no tray backend"

    step("the tray backend loads", tray_backend)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} Linux endpoint checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
