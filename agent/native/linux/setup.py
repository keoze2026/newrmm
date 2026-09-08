"""Build the native Linux capture module.

    python setup.py build_ext --inplace

Needs libx11, libxext (for MIT-SHM) and libxrandr development headers:

    sudo apt install libx11-dev libxext-dev libxrandr-dev

PipeWire support is compiled in when its headers are present, which adds the
Wayland path the specification calls for:

    sudo apt install libpipewire-0.3-dev
"""
import subprocess
import sys

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


def has_pipewire() -> bool:
    try:
        return subprocess.run(
            ["pkg-config", "--exists", "libpipewire-0.3"], check=False
        ).returncode == 0
    except OSError:
        return False


packages = ["x11", "xext", "xrandr"]
define_macros = []

if has_pipewire():
    packages.append("libpipewire-0.3")
    define_macros.append(("RMM_HAVE_PIPEWIRE", "1"))
    print("building with PipeWire support (Wayland path enabled)")
else:
    print(
        "libpipewire-0.3 headers not found: building the X11 path only.\n"
        "  install with: sudo apt install libpipewire-0.3-dev",
        file=sys.stderr,
    )

flags = pkg_config(*packages)

setup(
    name="rmm_capture_linux",
    version="0.1.0",
    description="Native X11 XShm / PipeWire screen capture for the endpoint agent",
    ext_modules=[
        Extension(
            "rmm_capture_linux",
            sources=["rmm_capture_linux.c"],
            define_macros=define_macros,
            extra_compile_args=["-O2", "-Wall", "-Wextra", *flags["extra_compile_args"]],
            **{k: v for k, v in flags.items() if k != "extra_compile_args"},
        )
    ],
)
