"""LabelSession: Qt-free interaction state for the labelling tool.

Owns the frame list, the cursor, the currently-armed percentage, and the active
badge, and drives the LabelStore. Every mutation autosaves. The GUI is a thin
view over this — so the whole workflow (add/remove/classify/navigate/resume) is
testable without a display.
"""

from __future__ import annotations

from pathlib import Path

from bap.forge.labeling.model import VALID_PCTS, Badge, FrameLabel, LabelStore


class LabelSession:
    def __init__(self, frames: list[str], store: LabelStore):
        if not frames:
            raise ValueError("LabelSession needs at least one frame.")
        self._frames = list(frames)
        self._store = store
        self._store.ensure_all(self._frames)
        self._index = self._first_unreviewed()
        self._armed_pct: int | None = None
        self._active: int | None = None  # index into current frame's badges

    # --- navigation ---------------------------------------------------------

    @property
    def store(self) -> LabelStore:
        return self._store

    @property
    def index(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self._frames)

    @property
    def armed_pct(self) -> int | None:
        return self._armed_pct

    @property
    def active_index(self) -> int | None:
        return self._active

    def current_file(self) -> str:
        return self._frames[self._index]

    def current(self) -> FrameLabel:
        return self._store.ensure(self.current_file())

    def badges(self) -> list[Badge]:
        return self.current().badges

    def _first_unreviewed(self) -> int:
        for i, file in enumerate(self._frames):
            label = self._store.get(file)
            if label is None or not label.reviewed:
                return i
        return 0  # all reviewed: start at the top for a re-check

    def goto(self, index: int) -> None:
        self._index = max(0, min(index, len(self._frames) - 1))
        self._active = None

    def next(self) -> None:
        self.goto(self._index + 1)

    def prev(self) -> None:
        self.goto(self._index - 1)

    def reviewed_count(self) -> int:
        return self._store.reviewed_count()

    # --- editing (each autosaves) ------------------------------------------

    def arm_pct(self, pct: int | None) -> None:
        """Set the percentage the next click will use. A concrete value is also
        applied to the active badge (the click-then-key flow); arming None only
        clears the armed value and never wipes an existing classification."""
        if pct is not None and pct not in VALID_PCTS:
            raise ValueError(f"pct must be one of {VALID_PCTS} or None.")
        self._armed_pct = pct
        if pct is None:
            return
        badges = self.badges()
        if self._active is not None and 0 <= self._active < len(badges):
            badges[self._active].pct = pct
            self._save()

    def add_badge(self, cx: int, cy: int) -> Badge:
        """Add a badge centre using the armed percentage; it becomes active."""
        badge = Badge(cx=cx, cy=cy, pct=self._armed_pct)
        self.badges().append(badge)
        self._active = len(self.badges()) - 1
        self._save()
        return badge

    def select_nearest(self, cx: int, cy: int, radius: int = 40) -> int | None:
        """Make the badge nearest to (cx,cy) within `radius` active; return its
        index, or None if nothing is close enough."""
        best_i, best_d2 = None, radius * radius
        for i, b in enumerate(self.badges()):
            d2 = (b.cx - cx) ** 2 + (b.cy - cy) ** 2
            if d2 <= best_d2:
                best_i, best_d2 = i, d2
        self._active = best_i
        return best_i

    def remove_active(self) -> bool:
        if self._active is None:
            return False
        badges = self.badges()
        if 0 <= self._active < len(badges):
            badges.pop(self._active)
            self._active = None
            self._save()
            return True
        self._active = None
        return False

    def remove_nearest(self, cx: int, cy: int, radius: int = 40) -> bool:
        if self.select_nearest(cx, cy, radius) is None:
            return False
        return self.remove_active()

    def set_reviewed(self, reviewed: bool = True) -> None:
        self.current().reviewed = reviewed
        self._save()

    def weakening(self) -> int | None:
        return self.current().weakening

    def set_weakening(self, value: int | None) -> None:
        """Set the ground-truth current-weakening value for this frame; autosave."""
        self.current().weakening = int(value) if value is not None else None
        self._save()

    def accept_suggestions(self, candidates: list[tuple[int, int]]) -> int:
        """Add any suggested centres not already near an existing badge (pct
        left None for the user to classify). Returns how many were added."""
        added = 0
        for cx, cy in candidates:
            if self.select_nearest(cx, cy, radius=30) is None:
                self.badges().append(Badge(cx=int(cx), cy=int(cy), pct=None))
                added += 1
        self._active = None
        if added:
            self._save()
        return added

    def unclassified(self) -> int:
        """Badges on the current frame still missing a percentage."""
        return sum(1 for b in self.badges() if b.pct is None)

    def _save(self) -> None:
        # Respect the store's autosave flag: Review Mode disables it so edits reach
        # disk only on an explicit Save (making Discard-on-close meaningful).
        if getattr(self._store, "autosave", True):
            self._store.save()

    @classmethod
    def open(cls, frames_dir: Path | str, labels_path: Path | str) -> "LabelSession":
        """Build a session over the PNGs in `frames_dir`, resuming `labels_path`."""
        frames_dir = Path(frames_dir)
        frames = sorted(p.name for p in frames_dir.glob("*.png"))
        if not frames:
            raise ValueError(f"No .png frames found in {frames_dir}.")
        return cls(frames, LabelStore.load(labels_path))


__all__ = ["LabelSession"]
