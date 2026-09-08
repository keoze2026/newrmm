"""Locates and loads the per-OS native capture module.

The specification requires a native capture module per platform, exposed to the
agent as a Python module:

    Windows   Rust, via the windows-capture / Windows.Graphics.Capture binding
    macOS     Swift/Obj-C, with ScreenCaptureKit
    Linux     C, with PipeWire / X11 XShm

Each is built separately (see agent/native/<os>/), so the agent may or may not
find one. When it does, that module does the capturing; when it does not, the
agent falls back to mss, which is the cross-platform core capture the build
prompt specifies.
"""
import importlib
import logging
import platform
import sys
from pathlib import Path

log = logging.getLogger(__name__)

MODULE_FOR_SYSTEM = {
    "Linux": "rmm_capture_linux",
    "Windows": "rmm_capture_windows",
    "Darwin": "rmm_capture_macos",
}

SOURCE_DIR_FOR_SYSTEM = {
    "Linux": "linux",
    "Windows": "windows",
    "Darwin": "macos",
}


def _search_paths() -> list[Path]:
    """Where a built module may sit: beside the package, in its build tree, or
    next to a PyInstaller bundle."""
    here = Path(__file__).resolve().parent
    directory = SOURCE_DIR_FOR_SYSTEM.get(platform.system(), "")
    candidates = [
        here,                                   # installed beside the package
        here.parent / "native" / directory,     # built in place
        Path(getattr(sys, "_MEIPASS", here)),   # inside a PyInstaller bundle
    ]
    return [path for path in candidates if path.is_dir()]


def load():
    """Return the native capture module, or None if it is not built here."""
    name = MODULE_FOR_SYSTEM.get(platform.system())
    if not name:
        return None

    try:
        return importlib.import_module(name)
    except ImportError:
        pass

    for path in _search_paths():
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
        try:
            module = importlib.import_module(name)
            log.info("loaded the native capture module from %s", path)
            return module
        except ImportError:
            continue

    log.info(
        "no native capture module for %s; using the mss core capture. "
        "Build it with: python agent/native/%s/",
        platform.system(), SOURCE_DIR_FOR_SYSTEM.get(platform.system(), "?"),
    )
    return None


def describe() -> str:
    """One line about which capture path is in use, for `status`."""
    module = load()
    if module is None:
        return "mss (no native module built)"
    try:
        return f"native {module.backend()}"
    except Exception:
        return "native"
