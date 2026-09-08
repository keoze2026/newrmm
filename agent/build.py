"""Build a standalone executable of the endpoint agent.

PyInstaller cannot cross-compile, so run this ON the machine you are building
for:

    python -m pip install -r requirements.txt pyinstaller
    python build.py

Output:
    Windows   dist/rmm-agent.exe
    macOS     dist/rmm-agent           (and dist/RMM Agent.app with --app)
    Linux     dist/rmm-agent

These are unsigned. Windows SmartScreen will warn, and macOS Gatekeeper will
refuse until the binary is signed and notarised - that is Phase 6.
"""
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "rmm-agent"
SYSTEM = platform.system()

# The native capture module the specification requires, per platform. Built
# separately (see agent/native/<os>/) and bundled here when present.
NATIVE_ARTEFACTS = {
    "Linux": ("native/linux", ["rmm_capture_linux*.so"]),
    "Windows": ("native/windows", ["rmm_capture_windows*.pyd", "target/release/*.dll"]),
    "Darwin": ("native/macos", ["libRMMCapture.dylib", "rmm_capture_macos.py"]),
}


def native_binaries() -> list[str]:
    """--add-binary arguments for the native module, if it has been built."""
    directory, patterns = NATIVE_ARTEFACTS.get(SYSTEM, ("", []))
    if not directory:
        return []
    source = ROOT / directory
    separator = ";" if SYSTEM == "Windows" else ":"
    found = []
    for pattern in patterns:
        for path in source.glob(pattern):
            found.append(f"{path}{separator}.")
    if not found:
        print(
            f"WARNING: no native capture module found in {source}.\n"
            "         The agent will fall back to mss. Build it first - see\n"
            "         docs/BUILDING_AGENTS.md.",
            file=sys.stderr,
        )
    return found

# pystray and pynput pick their backend at runtime, so PyInstaller cannot see
# the imports it needs to bundle.
HIDDEN = {
    "Windows": ["pystray._win32", "pynput.keyboard._win32", "pynput.mouse._win32"],
    "Darwin": ["pystray._darwin", "pynput.keyboard._darwin", "pynput.mouse._darwin"],
    "Linux": [
        "pystray._xorg", "pystray._appindicator", "pystray._gtk",
        "pynput.keyboard._xorg", "pynput.mouse._xorg",
    ],
}


def check_dependencies() -> bool:
    missing = []
    for module in ("websockets", "mss", "PIL", "pynput", "pystray"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    try:
        __import__("PyInstaller")
    except ImportError:
        missing.append("pyinstaller")
    if missing:
        print("Missing: " + ", ".join(missing), file=sys.stderr)
        print(f"Install with: {sys.executable} -m pip install -r requirements.txt pyinstaller",
              file=sys.stderr)
        return False
    return True


def build(app_bundle: bool, windowed: bool) -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        "--collect-submodules", "pynput",
        "--collect-submodules", "pystray",
    ]

    command.append("--windowed" if windowed else "--console")
    command.append("--onedir" if (app_bundle and SYSTEM == "Darwin") else "--onefile")

    for module in HIDDEN.get(SYSTEM, []):
        command += ["--hidden-import", module]

    for binary in native_binaries():
        command += ["--add-binary", binary]
        print(f"bundling native capture module: {binary.rsplit(':', 1)[0].rsplit(';', 1)[0]}")

    if SYSTEM == "Darwin" and app_bundle:
        # Screen Recording and Accessibility prompts need a real bundle
        # identifier, or macOS attributes the request to the terminal instead.
        command += ["--osx-bundle-identifier", "com.rmm.agent"]

    command.append(str(ROOT / "rmm_agent" / "__main__.py"))

    print(" ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    produced = ROOT / "dist" / (NAME + (".exe" if SYSTEM == "Windows" else ""))
    print(f"\nbuilt: {produced if produced.exists() else ROOT / 'dist'}")

    # A platform-suffixed copy so all three builds can share one directory,
    # which is what CI collects and what the relay hands to guests.
    if produced.exists():
        suffix = {"Windows": "windows.exe", "Darwin": "macos", "Linux": "linux"}[SYSTEM]
        tagged = produced.parent / f"{NAME}-{suffix}"
        shutil.copy2(produced, tagged)
        print(f"also: {tagged}")
    if SYSTEM == "Darwin":
        print(
            "\nmacOS: the first run needs Screen Recording and Accessibility "
            "permission in System Settings > Privacy & Security.\n"
            "Screen Recording only takes effect after the agent is restarted."
        )
    if SYSTEM == "Windows":
        print("\nWindows: unsigned, so SmartScreen will warn on first run.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app", action="store_true",
        help="macOS: build a .app bundle, needed for the permission prompts",
    )
    parser.add_argument(
        "--windowed", action="store_true",
        help="hide the console window (the terminal consent fallback goes with it)",
    )
    args = parser.parse_args()

    if SYSTEM not in ("Windows", "Darwin", "Linux"):
        print(f"Unsupported platform: {SYSTEM}", file=sys.stderr)
        return 2
    if not check_dependencies():
        return 2
    if shutil.which("git") is None:
        pass  # not required, just noted

    print(f"building the endpoint agent for {SYSTEM}")
    return build(app_bundle=args.app, windowed=args.windowed)


if __name__ == "__main__":
    raise SystemExit(main())
