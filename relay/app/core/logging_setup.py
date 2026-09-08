"""Persistent file logging for the relay (Phase 6).

The agent has kept a rotating log since Phase 2; the relay had only whatever
uvicorn printed to the console, which a container throws away on restart. This
adds a rotating file alongside it, and a request log that records who did what.

The audit trail in the database is the record of *sessions and administrative
actions*; this is the operational log - errors, timings, connections - and the
two are deliberately separate.
"""
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Paths that would otherwise fill the log with noise: the console polls the
# session list every few seconds and health is polled by the container runtime.
QUIET_PATHS = {"/health"}


def configure(log_dir: str, level: str = "INFO") -> Path | None:
    """Attach a rotating file handler to the root logger."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(stream)

    if not log_dir:
        return None

    try:
        directory = Path(log_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "relay.log"
        rotating = RotatingFileHandler(
            path, maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        rotating.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(rotating)
        logging.getLogger(__name__).info("logging to %s", path)
        return path
    except OSError as exc:
        # A relay that cannot write its log should still serve sessions.
        logging.getLogger(__name__).warning("could not open the log file: %s", exc)
        return None


class RequestLogMiddleware(BaseHTTPMiddleware):
    """One line per request: method, path, status and how long it took."""

    def __init__(self, app, logger_name: str = "relay.request") -> None:
        super().__init__(app)
        self.log = logging.getLogger(logger_name)

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            self.log.exception(
                "%s %s failed after %.0fms", request.method, request.url.path, elapsed
            )
            raise

        elapsed = (time.perf_counter() - started) * 1000
        if request.url.path not in QUIET_PATHS:
            level = logging.WARNING if response.status_code >= 500 else logging.INFO
            client = request.client.host if request.client else "-"
            self.log.log(
                level,
                "%s %s %s %.0fms from %s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
                client,
            )
        return response
