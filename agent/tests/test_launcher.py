"""What a non-technical person goes through: a code, checked, then consent."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rmm_agent import launcher  # noqa: E402


# ---------------------------------------------------------------- the code
def test_codes_ignore_case_spaces_and_dashes():
    """They are read aloud and typed by hand."""
    assert launcher.normalise_code("xz3z pqvk") == "XZ3ZPQVK"
    assert launcher.normalise_code(" XZ3Z-PQVK ") == "XZ3ZPQVK"
    assert launcher.normalise_code("") == ""
    assert launcher.normalise_code(None) == ""


# ------------------------------------------------------------- the address
@pytest.mark.parametrize("typed,expected", [
    ("support.example.com", "wss://support.example.com/api"),
    ("https://support.example.com", "wss://support.example.com/api"),
    ("https://support.example.com/", "wss://support.example.com/api"),
    ("http://10.0.0.5:8080", "ws://10.0.0.5:8080/api"),
    ("wss://support.example.com/api", "wss://support.example.com/api"),
    ("", ""),
])
def test_a_typed_server_becomes_the_relay_address(typed, expected):
    assert launcher.to_ws(typed) == expected


def test_the_relay_address_maps_back_to_http_for_checking_a_code():
    assert launcher.to_http("wss://a.example.com/api") == "https://a.example.com/api"
    assert launcher.to_http("ws://127.0.0.1:8000") == "http://127.0.0.1:8000"


# ------------------------------------------------------------ the server
class _Server:
    """A stand-in relay that answers the code lookup."""

    def __init__(self, behaviour):
        self.behaviour = behaviour

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):  # noqa: N805
                status = behaviour.get(handler.path.rsplit("/", 1)[-1], 404)
                handler.send_response(status)
                handler.end_headers()
                handler.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"ws://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc):
        self.httpd.shutdown()


def test_a_real_code_is_accepted():
    with _Server({"GOODCODE": 200}) as relay:
        assert launcher.check_code(relay, "GOODCODE") == (True, "")


def test_an_unknown_or_expired_code_gets_a_plain_explanation():
    with _Server({}) as relay:
        ok, message = launcher.check_code(relay, "NOPE1234")
    assert not ok
    assert "not valid" in message and "new one" in message


def test_too_many_attempts_says_to_wait():
    with _Server({"BUSY1234": 429}) as relay:
        ok, message = launcher.check_code(relay, "BUSY1234")
    assert not ok and "wait" in message.lower()


def test_an_unreachable_server_says_so_rather_than_blaming_the_code():
    ok, message = launcher.check_code("ws://127.0.0.1:9", "ABCD1234", timeout=2)
    assert not ok and "internet" in message.lower()


def test_a_code_that_is_too_short_is_rejected_without_asking_the_server():
    ok, message = launcher.check_code("ws://127.0.0.1:9", "AB")
    assert not ok and "short" in message


# ------------------------------------------------- straight to consent
def test_a_valid_code_from_the_download_skips_the_window(monkeypatch):
    """Download, install, done: the window is never shown."""
    asked = []
    monkeypatch.setattr(launcher, "ask", lambda *a, **k: asked.append(a) or None)

    with _Server({"XZ3ZPQVK": 200}) as relay:
        assert launcher.resolve(relay, "xz3zpqvk") == ("XZ3ZPQVK", relay)
    assert asked == [], "a valid code should not have asked anything"


def test_an_expired_code_falls_back_to_asking_and_says_why(monkeypatch):
    seen = {}

    def fake_ask(relay, prefill="", notice=""):
        seen.update(relay=relay, prefill=prefill, notice=notice)
        return None

    monkeypatch.setattr(launcher, "ask", fake_ask)
    with _Server({}) as relay:
        launcher.resolve(relay, "OLDCODE1")

    assert seen["prefill"] == "OLDCODE1"
    assert "expired" in seen["notice"]


def test_with_no_code_it_just_asks(monkeypatch):
    seen = {}
    monkeypatch.setattr(launcher, "ask", lambda *a, **k: seen.update(k=k, a=a) or None)
    launcher.resolve("wss://x.example.com/api", "")
    assert seen["k"].get("prefill") == ""
