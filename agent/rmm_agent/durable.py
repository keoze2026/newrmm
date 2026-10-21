"""Writes that survive the computer being switched off straight afterwards.

A plain write only reaches the operating system's cache. If the computer
restarts soon after, the file can come back with its name and no contents. The
agent's saved session was found at 0 bytes after exactly that, so the restart
service started, found nothing to rejoin, and exited without a word. A durable
write goes to a temporary file, is forced to disk, and only then replaces the
real one, so the file is always either the old contents or the new, never empty.
"""
import os
import sys
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if sys.platform != "win32":
        # The rename itself lives in the directory, so force that out too.
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass
