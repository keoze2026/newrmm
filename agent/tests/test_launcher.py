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


# ------------------------------------------------- straight to consent, no window
def test_the_code_from_the_download_is_used_as_is_with_no_window():
    """Download, install, done: the embedded code is used and no window exists.

    The person never types a code, so there is no code-input window at all."""
    assert not hasattr(launcher, "ask"), "the code-input window path must be gone"
    assert not hasattr(launcher, "_ask_with_window"), "the code-input window must be gone"
    assert launcher.resolve("wss://relay/api", "xz3z-pqvk") == ("XZ3ZPQVK", "wss://relay/api")


def test_with_no_code_there_is_nothing_to_do():
    """No code (or no server) means nothing to do - the agent stops quietly,
    it never pops a window asking for one."""
    assert launcher.resolve("wss://relay/api", "") is None
    assert launcher.resolve(None, "ABCD1234") is None
