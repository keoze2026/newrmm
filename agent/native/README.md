# Native capture modules

The specification requires a native screen-capture module per platform, exposed
to the agent as a Python module:

> **§5** Screen capture | Windows.Graphics.Capture (native) | ScreenCaptureKit | PipeWire (Wayland) / X11 XShm
>
> **§6** a cross-platform core plus a small native capture module per OS (Windows
> native module in RUST via the windows-capture / Windows.Graphics.Capture
> binding, exposed to the agent as a Python module; macOS in Swift/Obj-C with
> ScreenCaptureKit; Linux in C with PipeWire/X11)

| Platform | Language | API | Directory | Status |
| --- | --- | --- | --- | --- |
| Linux | C | X11 XShm (PipeWire when its headers are present) | `linux/` | **Built and verified on this machine** |
| Windows | Rust | Windows.Graphics.Capture via `windows-capture` | `windows/` | Written; compiles only on Windows |
| macOS | Swift | ScreenCaptureKit | `macos/` | Written; compiles only on macOS |

All three present the same interface, so `rmm_agent/capture.py` treats them
alike:

```python
open(index=0) -> str                    # backend name
monitors()    -> list[dict]             # index, label, width, height, left, top
grab(index=0) -> (bytes, width, height) # packed RGB, top row first
close()       -> None
backend()     -> str
```

`rmm_agent/native.py` finds and loads whichever is built. When none is, the
agent falls back to **mss**, the cross-platform core capture the build prompt
specifies — so the agent always runs, but the native path is preferred.

## Why native rather than a plain screen grab

The privacy blank is the reason. The guest's screen is covered with a black
window marked excluded from capture (`WDA_EXCLUDEFROMCAPTURE` on Windows,
`NSWindowSharingNone` on macOS). Only a compositor-level capture API honours
that exclusion and keeps delivering frames of the desktop *behind* the blank. A
GDI or CoreGraphics screen grab hands back the black window instead, which is
precisely the case §5 calls out.

On Linux there is no universal capture-exclusion, which is why the specification
prescribes the guest-lock variant there instead.

## Building

```bash
# Linux - needs libx11-dev libxext-dev libxrandr-dev
#         and optionally libpipewire-0.3-dev for the Wayland path
cd agent/native/linux && python setup.py build_ext --inplace

# Windows - needs the Rust toolchain and maturin
cd agent/native/windows && maturin build --release

# macOS - needs Xcode
cd agent/native/macos && ./build.sh
```

`agent/build.py` bundles whichever module it finds into the packaged agent.

## What is verified

The Linux module is built, run and benchmarked here: 164 fps of raw capture at
1920x1200, 62 fps end to end through the agent, against about 40 fps on mss.
`tests/e2e/p3_linux_endpoint.py` asserts the native path is the one in use.

The Windows and macOS modules have **not been compiled**. This machine has no
Windows Rust target (`rustup` is absent, so `x86_64-pc-windows-*` cannot be
added) and no Swift toolchain. Both were written against the real APIs — the
`windows-capture` 1.5 source was read to confirm every signature — but reading a
crate is not compiling it. They are unverified until built on those machines.
