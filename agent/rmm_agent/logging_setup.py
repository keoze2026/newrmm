"""Console and rotating-file logging, in the platform's state directory."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rmm_agent.config import state_dir

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure(verbose: bool = False) -> Path:
    path = state_dir() / "agent.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(stream)

    rotating = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    rotating.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(rotating)

    logging.getLogger("websockets").setLevel(logging.WARNING)
    return path
