"""Agent configuration and the on-disk state an enrolled device keeps."""
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path

from rmm_agent import durable


def state_dir() -> Path:
    """Per-user state, in the place each OS expects."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "RMMAgent"
    path.mkdir(parents=True, exist_ok=True)
    return path


try:
    # Written by build.py from RMM_DEFAULT_RELAY, so an agent built for a
    # server already knows where that server is and nobody has to type it.
    from rmm_agent import _baked  # type: ignore[attr-defined]

    BAKED_RELAY: str = getattr(_baked, "DEFAULT_RELAY", "") or ""
except ImportError:
    BAKED_RELAY = ""


def saved_relay() -> str:
    """The server last used, for builds that were not given one."""
    path = state_dir() / "last_relay.txt"
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def save_relay(relay: str) -> None:
    try:
        durable.write_text(state_dir() / "last_relay.txt", relay.strip())
    except OSError:
        pass


def default_relay() -> str:
    """Environment, then what was built in, then what was used last time."""
    return os.environ.get("RMM_RELAY", "").strip() or BAKED_RELAY or saved_relay()


@dataclass
class Enrolment:
    """Credentials for an unattended device, issued by the console."""

    device_id: str
    secret: str
    relay_url: str

    @classmethod
    def load(cls) -> "Enrolment | None":
        path = state_dir() / "enrolment.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls(data["device_id"], data["secret"], data["relay_url"])
        except (ValueError, KeyError):
            return None

    def save(self) -> Path:
        path = state_dir() / "enrolment.json"
        durable.write_text(path, json.dumps(self.__dict__, indent=2))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Windows ACLs differ; the file still sits in the user profile.
        return path
