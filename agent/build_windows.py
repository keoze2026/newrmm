"""Build a single-file Windows executable for the endpoint agent.

Run this ON the Windows machine (PyInstaller cannot cross-compile):

    py -m pip install -r agent/requirements.txt pyinstaller
    py agent/build_windows.py

The signed installer is Phase 6; this produces an unsigned .exe for testing, so
SmartScreen will warn on first run.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "rmm-agent"


def main() -> int:
    if sys.platform != "win32":
        print("This build script must run on Windows.", file=sys.stderr)
        return 2

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        # --noconsole would hide the fallback consent prompt, so keep a console
        # until the tray and dialog are proven on the target machine.
        "--name", NAME,
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-submodules", "pynput",
        str(ROOT / "rmm_agent" / "__main__.py"),
    ]
    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode == 0:
        print(f"\nbuilt: {ROOT / 'dist' / (NAME + '.exe')}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
