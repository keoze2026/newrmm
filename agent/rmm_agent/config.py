"""Agent configuration and the on-disk state an enrolled device keeps."""
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path


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
        path.write_text(json.dumps(self.__dict__, indent=2))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Windows ACLs differ; the file still sits in the user profile.
        return path
