"""A privacy blank that ends at the endpoint must be reported to the operator.

Scan finding: the watchdog and Escape released the blank without a word, so the
console kept saying "blanked"; and `--blank-watchdog 0` promised "off" while it
quietly meant 120 s. No overlay is drawn here.
"""
import asyncio
import json

from rmm_agent import privacy
from rmm_agent.session import AgentSession


def test_zero_means_the_default_limit_never_no_limit():
    assert privacy.PrivacyBlank(watchdog_seconds=0).watchdog_seconds == 120.0
    assert privacy.PrivacyBlank(watchdog_seconds=-5).watchdog_seconds == 120.0
    assert privacy.PrivacyBlank(watchdog_seconds=30).watchdog_seconds == 30.0


def test_a_release_at_the_endpoint_is_reported_with_its_reason(monkeypatch):
    seen = []
    blank = privacy.PrivacyBlank(watchdog_seconds=30, on_release=lambda r, s: seen.append((r, s)))
    blank.active = True
    monkeypatch.setattr(blank, "disable", lambda: (setattr(blank, "active", False), {"active": False})[1])
    blank._release("watchdog")
    assert seen == [("watchdog", {"active": False})]
    blank._release("escape")  # already off: nothing more to report
    assert len(seen) == 1


def test_the_watchdog_reports_when_it_releases(monkeypatch):
    seen = []
    blank = privacy.PrivacyBlank(watchdog_seconds=0.05, on_release=lambda r, s: seen.append(r))
    blank.active = True
    monkeypatch.setattr(blank, "disable", lambda: (setattr(blank, "active", False), {"active": False})[1])
    blank._watchdog()
    assert seen == ["watchdog"]


def test_the_session_tells_the_operator(monkeypatch):
    session = AgentSession("ws://relay", "ABCD1234", synthetic=True, inject=False)
    sent = []

    class Socket:
        async def send(self, text):
            sent.append(json.loads(text))

    async def go():
        session._loop = asyncio.get_running_loop()
        session._socket = Socket()
        session._blank_released("escape", {"active": False, "mode": "excluded"})
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert sent == [{"type": "blank", "action": "state", "active": False, "mode": "excluded",
                     "released_by": "escape"}]
