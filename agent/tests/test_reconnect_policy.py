"""The retry rules that stop an agent from looping forever."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rmm_agent import consent  # noqa: E402
from rmm_agent import session  # noqa: E402


def test_a_connection_that_closes_quickly_keeps_slowing_down():
    delay = session.BACKOFF_START
    seen = []
    for _ in range(8):
        delay = session.next_backoff(delay, lasted=0.2)
        seen.append(delay)
    assert seen[:4] == [2.0, 4.0, 8.0, 16.0]
    assert max(seen) == session.BACKOFF_MAX


def test_the_delay_resets_only_after_a_connection_that_worked():
    assert session.next_backoff(30.0, lasted=session.HEALTHY_SECONDS + 1) == session.BACKOFF_START


def test_rejected_credentials_ended_sessions_and_refusals_stop_retrying():
    assert set(session.GIVE_UP_CODES) == {4401, 4403, 4404}
    assert 4409 not in session.GIVE_UP_CODES  # an old socket may linger briefly


def test_consent_without_a_terminal_is_a_refusal_not_a_crash(monkeypatch):
    monkeypatch.setattr(consent, "_ask_with_tk", lambda *a, **k: None)

    def no_stdin(_prompt=""):
        raise RuntimeError("lost sys.stdin")

    monkeypatch.setattr("builtins.input", no_stdin)
    assert consent.ask("CODE1234") is False
