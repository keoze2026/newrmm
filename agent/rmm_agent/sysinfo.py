"""What the endpoint reports about itself when it attaches to a session."""
import os
import platform
import socket

from rmm_agent import __version__


def platform_key() -> str:
    system = platform.system()
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(system, system.lower())


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def collect() -> dict:
    info = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.version() or platform.release(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "ip": local_ip(),
        "cpu": platform.processor() or platform.machine(),
        "agent_version": __version__,
    }
    try:
        import psutil

        info["cores"] = psutil.cpu_count(logical=True)
        info["memory"] = f"{round(psutil.virtual_memory().total / 1024 ** 3, 1)} GB"
    except Exception:
        info["cores"] = os.cpu_count()
    return info
