"""Ground-truth data model + persistence for the labelling tool.

The on-disk format (`labels.json`) is a stable, human-readable record of, per
frame, the badge centres and their percentages, plus whether a human has
reviewed the frame. It autosaves atomically after every edit so a crash never
loses work and the tool can resume exactly where it left off.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# The five Guild Battlegrounds weakening levels; a badge pct is one of these or
# None (placed but not yet classified).
VALID_PCTS: tuple[int, ...] = (20, 40, 60, 80, 100)

SCHEMA_VERSION = 1


class LabelError(ValueError):
    pass


@dataclass
class Badge:
    """One weakening badge: its centre in ORIGINAL image pixels and its
    percentage (None until the labeller assigns one)."""

    cx: int
    cy: int
    pct: int | None = None

    def __post_init__(self) -> None:
        self.cx = int(self.cx)
        self.cy = int(self.cy)
        if self.pct is not None:
            self.pct = int(self.pct)
            if self.pct not in VALID_PCTS:
                raise LabelError(f"pct must be one of {VALID_PCTS} or None, got {self.pct}.")

    def to_dict(self) -> dict:
        return {"cx": self.cx, "cy": self.cy, "pct": self.pct}

    @classmethod
    def from_dict(cls, data: dict) -> "Badge":
        return cls(cx=data["cx"], cy=data["cy"], pct=data.get("pct"))


@dataclass
class FrameLabel:
    """All badges for one frame, plus whether a human has confirmed it.

    `reviewed` is the grading gate: only reviewed frames count as ground truth.
    A frame may legitimately have zero badges (a negative) once reviewed.
    """

    file: str
    badges: list[Badge] = field(default_factory=list)
    reviewed: bool = False
    # Ground-truth current-weakening value read from the top bar for this frame
    # (the attrition counter, an integer that can exceed 100), or None if not set.
    weakening: int | None = None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "badges": [b.to_dict() for b in self.badges],
            "reviewed": self.reviewed,
            "weakening": self.weakening,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FrameLabel":
        weak = data.get("weakening")
        return cls(
            file=data["file"],
            badges=[Badge.from_dict(b) for b in data.get("badges", [])],
            reviewed=bool(data.get("reviewed", False)),
            weakening=int(weak) if weak is not None else None,
        )

    @property
    def fully_classified(self) -> bool:
        """Reviewed and every badge has a percentage (no dangling None)."""
        return self.reviewed and all(b.pct is not None for b in self.badges)


class LabelStore:
    """Ordered set of FrameLabels keyed by filename, persisted to labels.json.

    Autosaves after each mutation when bound to a path. Loading a missing file
    yields an empty store bound to that path (the first edit creates it)."""

    def __init__(self, path: Path | str | None = None, *, autosave: bool = True):
        self._path = Path(path) if path is not None else None
        self._frames: dict[str, FrameLabel] = {}
        # When False, per-edit autosave (LabelSession._save) is suppressed and the
        # caller must persist explicitly via save() — used by Review Mode so a
        # close can Discard cleanly and edits only reach disk on an explicit Save.
        # An explicit save() always writes regardless of this flag.
        self.autosave = autosave

    def bind(self, path: Path | str) -> None:
        """Bind the store to a labels path (so a later explicit save() writes there)."""
        self._path = Path(path)

    @property
    def path(self) -> Path | None:
        return self._path

    def __len__(self) -> int:
        return len(self._frames)

    def files(self) -> list[str]:
        return list(self._frames)

    def get(self, file: str) -> FrameLabel | None:
        return self._frames.get(file)

    def ensure(self, file: str) -> FrameLabel:
        """Return the frame's label, creating an empty one if absent. Does not
        save on its own (the caller saves after a real edit)."""
        label = self._frames.get(file)
        if label is None:
            label = FrameLabel(file=file)
            self._frames[file] = label
        return label

    def ensure_all(self, files: list[str]) -> None:
        """Register every frame (preserving existing labels and order)."""
        for file in files:
            self.ensure(file)

    def reviewed_count(self) -> int:
        return sum(1 for f in self._frames.values() if f.reviewed)

    def save(self) -> None:
        """Atomically write the store (no-op when path-less)."""
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "frames": [f.to_dict() for f in self._frames.values()],
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @classmethod
    def load(cls, path: Path | str) -> "LabelStore":
        path = Path(path)
        store = cls(path=path)
        if not path.exists():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return store
        for record in (data or {}).get("frames", []):
            try:
                label = FrameLabel.from_dict(record)
            except (KeyError, LabelError, TypeError):
                continue  # skip a bad record, keep the rest
            store._frames[label.file] = label
        return store


__all__ = [
    "VALID_PCTS",
    "Badge",
    "FrameLabel",
    "LabelError",
    "LabelStore",
]
