"""The secret the relay hands this computer when it joins an attended session.

The first computer to join a session is bound to it. From then on the relay
wants this secret on every reconnect, and when the person chooses "Always
allow", so someone else who has seen the code cannot take the session over or
enrol their own machine into it. It is kept on disk (owner-only) so a session
rejoined after a restart still proves it is the same computer.
"""
import json
import logging
import os

from rmm_agent import durable
from rmm_agent.config import state_dir

log = logging.getLogger(__name__)
# Codes are short-lived; a handful is plenty and keeps the file from growing.
KEEP = 20


def _path():
    return state_dir() / "guest_tokens.json"


def _load_all() -> dict:
    try:
        data = json.loads(_path().read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("could not read the saved session secrets: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load(code: str) -> str | None:
    value = _load_all().get(code.upper())
    return value if isinstance(value, str) and value else None


def save(code: str, token: str) -> None:
    data = _load_all()
    data.pop(code.upper(), None)
    data[code.upper()] = token
    while len(data) > KEEP:
        data.pop(next(iter(data)))
    _write(data)


def forget(code: str | None = None) -> None:
    if code is None:
        try:
            _path().unlink()
        except OSError:
            pass
        return
    data = _load_all()
    if data.pop(code.upper(), None) is not None:
        _write(data)


def _write(data: dict) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        durable.write_text(path, json.dumps(data))
        if os.name != "nt":
            os.chmod(path, 0o600)
    except OSError as exc:
        log.warning("could not save the session secret: %s", exc)
