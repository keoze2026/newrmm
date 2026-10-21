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
