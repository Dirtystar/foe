"""Local crash bundles — no external telemetry.

On a fatal, unexpected error the entry points write a self-contained JSON bundle
to the crashes directory capturing: timestamp, application version, OS/runtime
info, the exception and traceback, the last known operational status, and a
tail of recent log lines. Nothing leaves the machine; the bundle is a file the
beta user can attach to a report.

This is entry-layer operational plumbing, not a runtime component: it observes
logs and exceptions, and writes a file. Core/runtime code never imports it.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

_TAIL_CAPACITY = 300


class LogTailHandler(logging.Handler):
    """Keeps the last N formatted log lines in memory for crash bundles.
    Bounded (deque), never touches disk, and swallows its own formatting errors
    so logging can never crash the app."""

    def __init__(self, capacity: int = _TAIL_CAPACITY) -> None:
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # logging must never raise into the app
            pass

    def tail(self) -> list[str]:
        return list(self.buffer)


class CrashReporter:
    def __init__(self, *, version: str, crashes_dir: Path, log_tail: LogTailHandler) -> None:
        self._version = version
        self._crashes_dir = Path(crashes_dir)
        self._log_tail = log_tail
        self._last_status: str | None = None

    def set_status(self, status: str) -> None:
        """Record the latest operational status (starting/ready/degraded/...)."""
        self._last_status = status

    def build_bundle(
        self, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": self._version,
            "os": {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "sys_platform": sys.platform,
            },
            "last_status": self._last_status,
            "exception": {
                "type": exc_type.__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(exc_type, exc, tb)),
            },
            "log_tail": self._log_tail.tail(),
        }

    def write(
        self, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> Path | None:
        """Write a crash bundle. Returns its path, or None if writing failed
        (a crash reporter must never itself raise)."""
        try:
            self._crashes_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            path = self._crashes_dir / f"crash-{stamp}.json"
            bundle = self.build_bundle(exc_type, exc, tb)
            path.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
            return path
        except Exception:
            return None


def install(reporter: CrashReporter, *, set_excepthook: bool = False) -> CrashReporter:
    """Attach the log-tail handler to the root logger so recent lines are always
    available for a bundle. When `set_excepthook` is True (GUI, where exceptions
    can surface through sys.excepthook rather than a caught frame), also chain an
    excepthook that writes a bundle before the previous hook runs."""
    root = logging.getLogger()
    if reporter._log_tail not in root.handlers:
        root.addHandler(reporter._log_tail)

    if set_excepthook:
        previous = sys.excepthook

        def _hook(exc_type, exc, tb):
            reporter.write(exc_type, exc, tb)
            previous(exc_type, exc, tb)

        sys.excepthook = _hook
    return reporter


__all__ = ["CrashReporter", "LogTailHandler", "install"]
