"""Build the native Linux capture module - the X11 path.

    python setup.py build_ext --inplace

Needs libx11, libxext (for MIT-SHM), libxrandr and libxfixes (for the cursor
image - the guest's own cursor is otherwise never captured at all) development
headers:

    sudo apt install libx11-dev libxext-dev libxrandr-dev libxfixes-dev

The Wayland path does not go through this module at all - see
rmm_agent/wayland_portal.py and rmm_agent/wayland_capture.py, which need
PyGObject and GStreamer's pipewire plugin instead (python3-gi,
gstreamer1.0-pipewire), not a C toolchain.
"""
import subprocess

from setuptools import Extension, setup


def pkg_config(*packages) -> dict:
    """Compiler and linker flags for the given pkg-config packages."""
    flags: dict[str, list[str]] = {
        "include_dirs": [], "library_dirs": [], "libraries": [],
        "extra_compile_args": [], "extra_link_args": [],
    }
    try:
        output = subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", *packages], text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            f"pkg-config failed for {' '.join(packages)}: {exc}\n"
            "Install the development headers listed in this file's docstring."
        ) from exc

    for token in output.split():
        if token.startswith("-I"):
            flags["include_dirs"].append(token[2:])
        elif token.startswith("-L"):
            flags["library_dirs"].append(token[2:])
        elif token.startswith("-l"):
            flags["libraries"].append(token[2:])
        elif token.startswith("-Wl"):
            flags["extra_link_args"].append(token)
        else:
            flags["extra_compile_args"].append(token)
    return flags


flags = pkg_config("x11", "xext", "xrandr", "xfixes")

setup(
    name="rmm_capture_linux",
    version="0.1.0",
    description="Native X11 XShm screen capture for the endpoint agent",
    ext_modules=[
        Extension(
            "rmm_capture_linux",
            sources=["rmm_capture_linux.c"],
            extra_compile_args=["-O2", "-Wall", "-Wextra", *flags["extra_compile_args"]],
            **{k: v for k, v in flags.items() if k != "extra_compile_args"},
        )
    ],
)
