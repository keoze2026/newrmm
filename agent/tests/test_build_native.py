"""A built agent must carry the native capture module its platform needs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402
from rmm_agent import native  # noqa: E402


def test_windows_build_collects_the_rust_module_by_name():
    """The agent imports it by name at runtime, so PyInstaller only bundles it
    if told to. It was missing, and Windows silently used mss instead."""
    assert native.MODULE_FOR_SYSTEM["Windows"] in build.HIDDEN["Windows"]


def test_windows_does_not_bundle_a_dll_python_cannot_import():
    patterns = build.NATIVE_ARTEFACTS["Windows"][1]
    assert not any(pattern.endswith(".dll") for pattern in patterns)
