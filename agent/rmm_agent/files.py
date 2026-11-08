"""File browsing and transfer on the endpoint (spec feature: File transfer).

Transfers are chunked so a large file neither blocks the stream nor has to fit
in one message. Paths are resolved before use, so a traversal like `../..` is
still an ordinary absolute path the endpoint user could reach themselves - the
agent runs as that user and grants no more than their own access.
"""
import base64
import logging
import os
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# Read once at import, on the main thread: os.umask() can only be read by
# setting it, which is unsafe once other threads are creating files.
_UMASK = os.umask(0)
os.umask(_UMASK)

CHUNK = 256 * 1024
MAX_ENTRIES = 2000


def home() -> str:
    return str(Path.home())


def listing(path: str | None) -> dict:
    target = Path(path).expanduser() if path else Path.home()
    try:
        target = target.resolve()
    except OSError:
        target = Path.home()

    if not target.is_dir():
        return {"path": str(target), "error": "Not a directory", "entries": []}

    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if len(entries) >= MAX_ENTRIES:
                    break
                try:
                    stat = entry.stat(follow_symlinks=False)
                    entries.append(
                        {
                            "name": entry.name,
                            "dir": entry.is_dir(follow_symlinks=False),
                            "size": stat.st_size,
                            "modified": int(stat.st_mtime),
                        }
                    )
                except OSError:
                    continue
    except PermissionError:
        return {"path": str(target), "error": "Permission denied", "entries": []}
    except OSError as exc:
        return {"path": str(target), "error": str(exc), "entries": []}

    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries,
    }


def read_chunks(path: str):
    """Yield (base64 chunk, final) for a file, or raise OSError."""
    target = Path(path).expanduser().resolve()
    size = target.stat().st_size
    with target.open("rb") as handle:
        sent = 0
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            sent += len(block)
            yield base64.b64encode(block).decode("ascii"), sent >= size
    if size == 0:
        yield "", True


class Upload:
    """Accumulates chunks the operator sends, writing them straight to disk.

    The chunks go to a temporary file next to the target, which replaces the
    target only once the last chunk is in. Writing into the target directly
    emptied an existing file on the first chunk, and an interrupted re-upload
    then deleted it: the original was gone, not just the new copy.
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".part", dir=self.path.parent
        )
        self.temporary = Path(temporary)
        self.handle = os.fdopen(handle, "wb")
        self.written = 0

    def write(self, data_b64: str) -> None:
        block = base64.b64decode(data_b64)
        self.handle.write(block)
        self.written += len(block)

    def finish(self) -> dict:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        if self.path.exists():
            # Keep the permissions of the file being replaced.
            try:
                shutil.copymode(self.path, self.temporary)
            except OSError:
                pass
        else:
            # mkstemp makes it owner-only; give it what a new file normally gets.
            os.chmod(self.temporary, 0o666 & ~_UMASK)
        os.replace(self.temporary, self.path)
        log.info("received %s (%d bytes)", self.path, self.written)
        return {"path": str(self.path), "size": self.written}

    def abort(self) -> None:
        """Drop the partial copy. The original, if any, is untouched."""
        try:
            self.handle.close()
        except OSError:
            pass
        try:
            self.temporary.unlink(missing_ok=True)
        except OSError:
            pass
