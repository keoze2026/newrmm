"""Opening a chat window must not stall the session.

Scan finding: ChatWindow waited on "GUI unavailable" for 3 s, which never fires
when the GUI is fine, so every window cost the full 3 s on the event loop.
No real window is drawn here.
"""
import threading
import time

from rmm_agent import chat


def _fresh(monkeypatch, outcome):
    monkeypatch.setattr(chat, "_gui_available", threading.Event())
    monkeypatch.setattr(chat, "_gui_unavailable", threading.Event())
    monkeypatch.setattr(chat, "_gui_decided", threading.Event())
    monkeypatch.setattr(chat, "_commands", chat.queue.Queue())

    def start():
        def decide():
            time.sleep(0.05)
            (chat._gui_available if outcome else chat._gui_unavailable).set()
            chat._gui_decided.set()
        threading.Thread(target=decide, daemon=True).start()

    monkeypatch.setattr(chat, "_ensure_gui_thread", start)


def test_a_working_gui_does_not_cost_three_seconds(monkeypatch):
    _fresh(monkeypatch, outcome=True)
    started = time.monotonic()
    window = chat.ChatWindow(lambda text: None)
    assert time.monotonic() - started < 1.0
    assert window.available
    assert chat._commands.get_nowait()[0] == "create"


def test_no_gui_is_reported_quickly_too(monkeypatch):
    _fresh(monkeypatch, outcome=False)
    started = time.monotonic()
    window = chat.ChatWindow(lambda text: None)
    assert time.monotonic() - started < 1.0
    assert not window.available
