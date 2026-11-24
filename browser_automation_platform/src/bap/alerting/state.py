"""What we already told the group — so a restart, a re-entry into GBG, or a second snapshot
of the same map never double-posts the same opening.

A tiny JSON file: ``{"sent": {"<provinceId>:<opensAt>": <ts>}}``. Entries older than a day
are pruned on save, because a province that opened yesterday can never be announced again
(its key carries the timestamp).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_PATH = "alert_state.json"
_KEEP_SECONDS = 24 * 3600


class SentLog:
    """Remembers announced event keys, persisted best-effort (never raises)."""

    def __init__(self, path=DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._sent: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            sent = obj.get("sent") if isinstance(obj, dict) else None
            if isinstance(sent, dict):
                self._sent = {str(k): float(v) for k, v in sent.items()}
        except Exception:
            self._sent = {}

    @property
    def keys(self) -> frozenset:
        return frozenset(self._sent)

    def __contains__(self, key: str) -> bool:
        return key in self._sent

    def record(self, keys, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for k in keys:
            self._sent[str(k)] = now
        self.save(now=now)

    def save(self, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._sent = {k: v for k, v in self._sent.items() if now - v < _KEEP_SECONDS}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"sent": self._sent}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            pass                      # alerting must never die over a state file


__all__ = ["SentLog", "DEFAULT_PATH"]
