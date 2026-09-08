"""Python face of the native macOS capture module.

The Swift half (Sources/RMMCapture) exports C-ABI entry points; this loads the
dylib with ctypes and presents the same interface as the Linux C module and the
Windows Rust module, so the agent treats all three identically:

    open(index=0) -> str
    monitors()    -> list[dict]
    grab(index=0) -> (bytes, width, height)
    close()       -> None
    backend()     -> str

Build the dylib first:  ./build.sh   (on a Mac, with Xcode)
"""
import ctypes
import platform
from pathlib import Path

LIBRARY_NAME = "libRMMCapture.dylib"

_lib = None
_opened_index = None


class NativeCaptureUnavailable(ImportError):
    """The dylib has not been built, or this is not macOS."""


def _find_library() -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (here / LIBRARY_NAME,
                      here / ".build" / "release" / LIBRARY_NAME,
                      Path.cwd() / LIBRARY_NAME):
        if candidate.exists():
            return candidate
    return None


def _load():
    global _lib
    if _lib is not None:
        return _lib

    if platform.system() != "Darwin":
        raise NativeCaptureUnavailable("the macOS capture module needs macOS")

    path = _find_library()
    if path is None:
        raise NativeCaptureUnavailable(
            f"{LIBRARY_NAME} has not been built; run agent/native/macos/build.sh"
        )

    lib = ctypes.CDLL(str(path))

    lib.rmm_capture_open.argtypes = [ctypes.c_int32]
    lib.rmm_capture_open.restype = ctypes.c_int32

    lib.rmm_capture_close.argtypes = []
    lib.rmm_capture_close.restype = None

    lib.rmm_capture_display_count.argtypes = []
    lib.rmm_capture_display_count.restype = ctypes.c_int32

    lib.rmm_capture_display_info.argtypes = [ctypes.c_int32,
                                             ctypes.POINTER(ctypes.c_int32)]
    lib.rmm_capture_display_info.restype = ctypes.c_int32

    lib.rmm_capture_frame_size.argtypes = [ctypes.POINTER(ctypes.c_int32)]
    lib.rmm_capture_frame_size.restype = ctypes.c_int32

    lib.rmm_capture_grab.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int32]
    lib.rmm_capture_grab.restype = ctypes.c_int32

    _lib = lib
    return _lib


def backend() -> str:
    return "screencapturekit"


def open(index: int = 0) -> str:  # noqa: A001 - matches the other native modules
    global _opened_index
    lib = _load()
    result = lib.rmm_capture_open(ctypes.c_int32(index))
    if result == -2:
        raise RuntimeError("ScreenCaptureKit needs macOS 12.3 or newer")
    if result != 0:
        raise RuntimeError(
            "could not start ScreenCaptureKit. The usual cause is Screen "
            "Recording permission: allow it in System Settings > Privacy & "
            "Security > Screen Recording, then restart the agent."
        )
    _opened_index = index
    return backend()


def monitors() -> list[dict]:
    lib = _load()
    count = lib.rmm_capture_display_count()
    found = []
    for index in range(count):
        out = (ctypes.c_int32 * 5)()
        if lib.rmm_capture_display_info(ctypes.c_int32(index), out) != 0:
            continue
        display_id, width, height, left, top = list(out)
        found.append({
            "index": index,
            "label": f"Display {display_id}",
            "width": int(width),
            "height": int(height),
            "left": int(left),
            "top": int(top),
        })
    return found


def grab(index: int = 0) -> tuple[bytes, int, int]:
    lib = _load()
    if _opened_index != index:
        open(index)

    size = (ctypes.c_int32 * 2)()
    if lib.rmm_capture_frame_size(size) != 0:
        raise RuntimeError("no frame has arrived yet")
    width, height = int(size[0]), int(size[1])

    capacity = width * height * 3
    buffer = (ctypes.c_uint8 * capacity)()
    written = lib.rmm_capture_grab(buffer, ctypes.c_int32(capacity))
    if written < 0:
        raise RuntimeError("could not read the latest frame")
    return bytes(bytearray(buffer)[:written]), width, height


def close() -> None:
    global _opened_index
    if _lib is not None:
        _lib.rmm_capture_close()
    _opened_index = None


def have_pipewire() -> bool:
    """Present for interface parity with the Linux module."""
    return False
