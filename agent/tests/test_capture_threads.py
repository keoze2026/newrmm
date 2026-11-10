"""Screen capture from a worker thread.

On Windows, mss keeps its device context in thread-local storage, so a capture
object made on one thread fails on another with
"'_thread._local' object has no attribute 'srcdc'". The agent grabs frames on
pool threads (asyncio.to_thread), so every connection died on its first frame.
This fake library fails the same way, on any OS.
"""
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rmm_agent import capture  # noqa: E402


class FakeShot:
    size = (2, 2)
    bgra = bytes(16)


class ThreadBoundMSS:
    def __init__(self):
        self._owner = threading.get_ident()
        self.monitors = [
            {"left": 0, "top": 0, "width": 2, "height": 2},
            {"left": 0, "top": 0, "width": 2, "height": 2},
        ]

    def grab(self, _monitor):
        if threading.get_ident() != self._owner:
            raise AttributeError("'_thread._local' object has no attribute 'srcdc'")
        return FakeShot()


def make_capture(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=ThreadBoundMSS))
    monkeypatch.setattr(capture.native_loader, "load", lambda: None)
    return capture.ScreenCapture()


def test_grabbing_on_a_worker_thread_works(monkeypatch):
    screen = make_capture(monkeypatch)
    assert screen.backend == "mss"
    with ThreadPoolExecutor(max_workers=1) as pool:
        image = pool.submit(screen.grab).result()
    assert image.size == (2, 2)


def test_grabbing_on_the_creating_thread_still_works(monkeypatch):
    screen = make_capture(monkeypatch)
    assert screen.grab().size == (2, 2)


def test_every_worker_thread_gets_its_own_capture_object(monkeypatch):
    screen = make_capture(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        sizes = [f.result().size for f in [pool.submit(screen.grab) for _ in range(6)]]
    assert sizes == [(2, 2)] * 6


class FakeNative:
    """A native capture module, as native_loader.load() returns one."""

    def __init__(self, backend="windows", monitors=None):
        self.backend = backend
        self._monitors = monitors or [{"index": 0, "label": "Primary", "width": 4, "height": 4, "left": 0, "top": 0}]
        self.closed = False

    def open(self):
        return self.backend

    def monitors(self):
        return self._monitors

    def grab(self, _index):
        return (bytes(4 * 4 * 3), 4, 4)

    def close(self):
        self.closed = True


def test_recover_rebuilds_a_dead_native_module_in_place(monkeypatch):
    first = FakeNative(backend="windows")
    second = FakeNative(backend="windows")
    handed = iter([first, second])
    monkeypatch.setattr(capture.native_loader, "load", lambda: next(handed))
    screen = capture.ScreenCapture()
    assert screen.backend == "native-windows"
    assert screen._native is first

    assert screen.recover() is True
    assert screen._native is second          # swapped in
    assert first.closed is True              # old one closed only after the new one opened
    assert screen.backend == "native-windows"


def test_recover_keeps_the_old_module_if_the_rebuild_fails(monkeypatch):
    first = FakeNative(backend="windows")

    class Broken(FakeNative):
        def open(self):
            raise RuntimeError("capture still unavailable")

    broken = Broken()
    handed = iter([first, broken])
    monkeypatch.setattr(capture.native_loader, "load", lambda: next(handed))
    screen = capture.ScreenCapture()

    assert screen.recover() is False         # could not rebuild
    assert screen._native is first           # kept the old handle to retry, not None
    assert first.closed is False             # old one NOT closed - still the live fallback
    assert broken.closed is True             # the failed new one was cleaned up


def test_recover_does_nothing_on_mss_so_non_native_paths_are_untouched(monkeypatch):
    screen = make_capture(monkeypatch)       # mss backend, no native
    assert screen.backend == "mss"
    assert screen.recover() is False
    assert screen.backend == "mss"


def test_recover_never_touches_an_attached_wayland_portal(monkeypatch):
    first = FakeNative(backend="x11")
    monkeypatch.setattr(capture.native_loader, "load", lambda: first)
    screen = capture.ScreenCapture()

    portal = types.SimpleNamespace(
        started=True,
        monitors=[{"index": 0, "label": "Primary", "width": 4, "height": 4, "left": 0, "top": 0}],
    )
    assert screen.attach_portal(portal) is True
    assert screen.backend == "wayland-portal"

    assert screen.recover() is False         # portal recovery is session.py's job
    assert screen._wayland is portal         # untouched
    assert screen.backend == "wayland-portal"
