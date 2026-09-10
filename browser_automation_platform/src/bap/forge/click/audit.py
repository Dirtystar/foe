"""Append-only audit log for the Open & Verify flow (Milestone 6A.1).

Every armed intent, the single executed click, panel detection, and the
independent panel verification outcome are recorded as JSON lines, so there is a
permanent, tamper-evident trail of every click the product ever performs.

Contrast with the M5A cursor audit (which stamps ``no_click=true``): this log
records a real click, so ``CLICK_EXECUTED`` carries ``click=true``. Crucially, the
pre-click ``CLICK_ARMED`` record is **fail-closed** — :meth:`record_or_raise`
propagates a write failure so the caller can refuse to click when it cannot leave a
trail (a missing click record is worse than a missed click).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Event vocabulary (exactly the six the milestone requires, plus a blocked/cancel
# record carried over from the M6 design for gate failures).
EVENT_CLICK_ARMED = "CLICK_ARMED"
EVENT_CLICK_EXECUTED = "CLICK_EXECUTED"
EVENT_CLICK_BLOCKED = "CLICK_BLOCKED"
EVENT_PANEL_DETECTED = "PANEL_DETECTED"
EVENT_PANEL_VERIFY_MATCH = "PANEL_VERIFY_MATCH"
EVENT_PANEL_VERIFY_MISMATCH = "PANEL_VERIFY_MISMATCH"
EVENT_PANEL_VERIFY_UNKNOWN = "PANEL_VERIFY_UNKNOWN"

ALL_EVENTS = (
    EVENT_CLICK_ARMED, EVENT_CLICK_EXECUTED, EVENT_CLICK_BLOCKED,
    EVENT_PANEL_DETECTED, EVENT_PANEL_VERIFY_MATCH, EVENT_PANEL_VERIFY_MISMATCH,
    EVENT_PANEL_VERIFY_UNKNOWN,
)


class ClickAudit:
    """Append-only JSONL writer for click events. One instance per log file."""

    def __init__(self, path: Path | str):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _record(self, event: str, entry: dict) -> None:
        record = {
            "event": event,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **entry,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record(self, event: str, entry: dict | None = None) -> None:
        """Append one record; audit-write failures are swallowed (best effort)."""
        try:
            self._record(event, entry or {})
        except Exception:  # never let a best-effort audit write affect the flow
            pass

    def record_or_raise(self, event: str, entry: dict | None = None) -> None:
        """Append one record, **propagating** any write failure. Used for the
        pre-click ``CLICK_ARMED`` intent so the caller can fail closed (no trail →
        no click)."""
        self._record(event, entry or {})

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        out: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


def default_click_audit_path():
    """The per-user click-audit path (``<data>/forge/click_audit.jsonl``)."""
    from bap.ops.paths import ensure_dirs, get_paths

    return ensure_dirs(get_paths()).data_dir / "forge" / "click_audit.jsonl"


__all__ = [
    "ClickAudit", "default_click_audit_path",
    "EVENT_CLICK_ARMED", "EVENT_CLICK_EXECUTED", "EVENT_CLICK_BLOCKED",
    "EVENT_PANEL_DETECTED", "EVENT_PANEL_VERIFY_MATCH",
    "EVENT_PANEL_VERIFY_MISMATCH", "EVENT_PANEL_VERIFY_UNKNOWN", "ALL_EVENTS",
]
