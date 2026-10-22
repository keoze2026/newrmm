"""An always-on agent: allow once, and the computer stays reachable.

The person chooses "Always allow" in the consent window. The agent enrols with
the relay, then stays online by itself - through sleep, network loss, a restart
- and starts a session when an operator opens it, without a window. Quit, or
`rmm-agent stop`, turns it off for good.
"""
import asyncio
import json
import sys
import types
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
import websockets  # noqa: E402

from rmm_agent import __main__ as agent  # noqa: E402
from rmm_agent import consent, device, enrol, macos_dialogs  # noqa: E402
from rmm_agent.config import Enrolment  # noqa: E402
from rmm_agent.session import AgentSession  # noqa: E402


# ------------------------------------------------------------ the consent window

def test_always_allow_is_a_third_choice_only_when_it_is_offered(monkeypatch):
    seen = {}

    def tk(code, operator, timeout, standing=False):
        seen["standing"] = standing
        return "always" if standing else True

    monkeypatch.setattr(consent, "_ask_with_tk", tk)
    assert consent.ask_choice("ABCD1234", standing=True) == "always"
    assert seen["standing"] is True
    assert consent.ask_choice("ABCD1234", standing=False) == "once"


def test_deny_and_a_plain_allow_still_work(monkeypatch):
    monkeypatch.setattr(consent, "_ask_with_tk", lambda *a, **k: False)
    assert consent.ask_choice("ABCD1234", standing=True) == "deny"
    assert consent.ask("ABCD1234") is False
    monkeypatch.setattr(consent, "_ask_with_tk", lambda *a, **k: True)
    assert consent.ask("ABCD1234") is True


def test_the_standing_offer_explains_what_it_means_and_how_to_turn_it_off():
    text = consent._message("ABCD1234", None, standing=True)
    assert "Always allow" in text and "any time" in text and "rmm-agent stop" in text
    assert "Always allow" not in consent._message("ABCD1234", None)


def test_macos_offers_the_same_three_choices(monkeypatch):
    def run(output):
        seen = {}

        def fake(command, **options):
            seen["script"] = command[2]
            return types.SimpleNamespace(stdout=output, stderr="", returncode=0)

        monkeypatch.setattr(macos_dialogs.subprocess, "run", fake)
        return seen

    seen = run("button returned:Always allow, gave up:false\n")
    assert macos_dialogs.consent("May we?", standing=True) == "always"
    assert '"Always allow"' in seen["script"] and '"Allow this time"' in seen["script"]
    run("button returned:Allow this time, gave up:false\n")
    assert macos_dialogs.consent("May we?", standing=True) is True
    run("button returned:Always allow, gave up:true\n")
    assert macos_dialogs.consent("May we?", standing=True) is False  # no answer in time is a refusal


# ---------------------------------------------------------------- enrolling

def fake_urlopen(monkeypatch, outcomes):
    calls = []

    def urlopen(request, timeout=0):
        calls.append(request.full_url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return types.SimpleNamespace(
            read=lambda: json.dumps(outcome).encode(),
            __enter__=lambda self=None: None,
        )

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    def real(request, timeout=0):
        calls.append(request.full_url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Response(outcome)

    monkeypatch.setattr(enrol.urllib.request, "urlopen", real)
    return calls


def conflict():
    return urllib.error.HTTPError("u", 409, "conflict", {}, None)


def test_enrolling_saves_the_device_the_relay_issues(monkeypatch):
    saved = []
    monkeypatch.setattr(Enrolment, "save", lambda self: saved.append(self))
    calls = fake_urlopen(monkeypatch, [{"device_id": "dev-1", "secret": "s3cret"}])
    result = enrol.enrol("wss://relay/api", "ABCD1234")
    assert result.device_id == "dev-1" and result.secret == "s3cret"
    assert result.relay_url == "wss://relay/api"
    assert saved == [result]
    assert calls == ["https://relay/api/connector/enrol"]


def test_enrolling_waits_for_the_relay_to_record_the_consent(monkeypatch):
    monkeypatch.setattr(Enrolment, "save", lambda self: None)
    monkeypatch.setattr(enrol.time, "sleep", lambda _s: None)
    calls = fake_urlopen(monkeypatch, [conflict(), conflict(), {"device_id": "d", "secret": "s"}])
    assert enrol.enrol("wss://relay/api", "ABCD1234") is not None
    assert len(calls) == 3


def test_enrolling_gives_up_cleanly_when_the_relay_keeps_refusing(monkeypatch):
    monkeypatch.setattr(Enrolment, "save", lambda self: pytest.fail("saved a device that was refused"))
    monkeypatch.setattr(enrol.time, "sleep", lambda _s: None)
    fake_urlopen(monkeypatch, [conflict()] * 5)
    assert enrol.enrol("wss://relay/api", "ABCD1234", attempts=5) is None


def test_enrolling_survives_no_network(monkeypatch):
    fake_urlopen(monkeypatch, [urllib.error.URLError("no route")])
    assert enrol.enrol("wss://relay/api", "ABCD1234") is None


# ---------------------------------------------------------- the session itself

def make_session(**options):
    return AgentSession("wss://relay/api", "ABCD1234", synthetic=True, inject=False, **options)


def test_after_always_allow_the_session_ending_is_no_longer_the_end():
    async def go():
        forgotten = []
        session = make_session(on_over=lambda: forgotten.append(1), on_standing=lambda: True)
        await session._enrol()
        assert session.enrolled is True
        session._over()
        assert forgotten == [], "ending the session must not turn the always-on agent off"

    asyncio.run(go())


def test_a_failed_enrolment_leaves_an_ordinary_session():
    async def go():
        forgotten = []
        session = make_session(on_over=lambda: forgotten.append(1), on_standing=lambda: False)
        await session._enrol()
        assert session.enrolled is False
        session._over()
        assert forgotten == [1]

    asyncio.run(go())


def test_a_session_an_enrolled_device_starts_never_reconnects_by_itself():
    session = make_session(standing_consent=True, single_shot=True)
    assert session.standing_consent and session.single_shot


# ------------------------------------------------------------- staying online

class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, text):
        self.sent.append(text)

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0.02)  # a real connection is open for a moment before it closes
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FakeConnect:
    def __init__(self, plan):
        self.plan = plan

    def __call__(self, url, **options):
        step = self.plan.pop(0)
        outer = self

        class Context:
            async def __aenter__(self_inner):
                if isinstance(step, Exception):
                    raise step
                return step

            async def __aexit__(self_inner, *_):
                return False

        return Context()


def run_serve(monkeypatch, plan, on_start=None, on_revoked=None, stop_after=None):
    stop = asyncio.Event()
    started = []

    async def default_start(code):
        started.append(code)

    async def go():
        monkeypatch.setattr(device.websockets, "connect", FakeConnect(plan))
        original_wait_for = asyncio.wait_for

        async def quick_wait(awaitable, timeout):
            if stop_after is not None and not plan:
                await asyncio.sleep(0.05)  # let a session that was just started take its first turn
                stop.set()
            return await original_wait_for(awaitable, 0.01)

        monkeypatch.setattr(device.asyncio, "wait_for", quick_wait)
        await original_wait_for(
            device.serve("wss://relay/api", "dev-1", "s3cret", on_start or default_start, stop,
                         on_revoked=on_revoked),
            timeout=10,
        )

    asyncio.run(go())
    return started


def test_an_operator_opening_the_session_starts_it_without_a_window(monkeypatch):
    socket = FakeSocket([json.dumps({"type": "start_session", "code": "ABCD1234"})])
    started = run_serve(monkeypatch, [socket], stop_after=True)
    assert started == ["ABCD1234"]
    assert json.loads(socket.sent[0])["type"] == "heartbeat"


def test_it_keeps_retrying_forever_after_the_network_goes(monkeypatch):
    """Sleep, a dead network, the relay restarting: it must come back by itself."""
    socket = FakeSocket([json.dumps({"type": "start_session", "code": "AFTER123"})])
    plan = [OSError("network is unreachable"), TimeoutError("timed out"), ConnectionResetError(), socket]
    started = run_serve(monkeypatch, plan, stop_after=True)
    assert started == ["AFTER123"]


def test_it_stops_and_says_so_when_the_relay_removes_the_device(monkeypatch):
    response = websockets.http11.Response(403, "Forbidden", websockets.Headers())
    revoked = []
    run_serve(monkeypatch, [websockets.InvalidStatus(response)], on_revoked=lambda: revoked.append(1))
    assert revoked == [1]


def test_a_second_request_while_a_session_runs_is_ignored(monkeypatch):
    messages = [json.dumps({"type": "start_session", "code": "FIRST123"}),
                json.dumps({"type": "start_session", "code": "SECOND12"})]
    started = []

    async def long_session(code):
        started.append(code)
        await asyncio.sleep(5)

    run_serve(monkeypatch, [FakeSocket(messages)], on_start=long_session, stop_after=True)
    assert started == ["FIRST123"]


# -------------------------------------------------------------- the off switch

def test_the_off_switch_forgets_both_the_restart_and_the_enrolment(monkeypatch):
    calls = []
    monkeypatch.setattr(agent.autostart, "forget", lambda code=None, always=False, **k: calls.append(("forget", always)))
    monkeypatch.setattr(agent.Enrolment, "delete", classmethod(lambda cls: calls.append(("delete",))))
    agent.turn_off()
    assert calls == [("forget", True), ("delete",)]


def test_a_restart_of_an_enrolled_computer_goes_straight_back_to_always_online(monkeypatch):
    enrolment = Enrolment("dev-1", "s3cret", "wss://relay/api")
    monkeypatch.setattr(agent.Enrolment, "load", classmethod(lambda cls: enrolment))
    monkeypatch.setattr(agent.launcher, "hide_console_if_owned", lambda: None)
    monkeypatch.setattr(agent.background, "write_pid", lambda: None)
    monkeypatch.setattr(agent.background, "clear_pid", lambda: None)
    ran = {}
    monkeypatch.setattr(agent, "_run_with_tray", lambda factory, use_tray, on_user_quit=None: ran.update(tray=use_tray) or 0)
    monkeypatch.setattr(agent, "cmd_join", lambda a: pytest.fail("rejoined an old session instead of staying online"))
    assert agent.cmd_resume(None) == 0
    assert ran == {"tray": True}
