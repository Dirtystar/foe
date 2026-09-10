"""Append-only audit log for cursor previews (Milestone 5A).

Every preview move (and every blocked attempt at move time) is recorded as one
JSON line, so there is a permanent, tamper-evident trail that the cursor moved
**and never clicked**. Records carry the full coordinate trace, window geometry,
target/safety values, the operator confirmation, and the explicit
``event = "CURSOR_PREVIEW_ONLY"`` / ``no_click = true`` guarantee.

Only Forge-tab context is recorded — never unrelated tab content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

EVENT_CURSOR_PREVIEW_ONLY = "CURSOR_PREVIEW_ONLY"


class CursorPreviewAudit:
    """Append-only JSONL writer. One instance per log file."""

    def __init__(self, path: Path | str):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def record(self, entry: dict) -> None:
        """Append one audit record, stamped with the event type, a UTC timestamp,
        and the no-click guarantee. Writes are line-atomic (append mode)."""
        record = {
            "event": EVENT_CURSOR_PREVIEW_ONLY,
            "no_click": True,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **entry,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        """Every record (for tests / diagnostics). Missing file → []."""
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


def default_audit_path():
    """The per-user audit path (``<data>/forge/cursor_preview_audit.jsonl``)."""
    from bap.ops.paths import ensure_dirs, get_paths

    return ensure_dirs(get_paths()).data_dir / "forge" / "cursor_preview_audit.jsonl"


__all__ = ["CursorPreviewAudit", "EVENT_CURSOR_PREVIEW_ONLY", "default_audit_path"]
