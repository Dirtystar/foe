"""Bulk review-assist actions (Milestone 5D) — suggestions the operator applies.

Pure functions over a :class:`FrameLabel`; the operator's label is ground truth and
**no action ever marks a frame reviewed**. "Detector suggestions" come from the
existing detector/classifier via a scan — they only propose positions/classes.
"""

from __future__ import annotations

from bap.forge.labeling.model import VALID_PCTS, Badge, FrameLabel


def _positions_from_scan(scan) -> list[tuple[int, int, int | None]]:
    out = []
    for d in getattr(scan, "detections", []):
        pct = getattr(d, "pct", None)
        out.append((int(d.cx), int(d.cy), pct if pct in VALID_PCTS else None))
    return out


def accept_all_positions(label: FrameLabel, scan) -> int:
    """Seed every detected position as a badge with **no class assigned**. Existing
    badges are replaced by the detector's positions. Never marks reviewed. Returns
    the number of positions accepted."""
    positions = _positions_from_scan(scan)
    label.badges = [Badge(cx=x, cy=y, pct=None) for x, y, _p in positions]
    return len(label.badges)


def remove_all(label: FrameLabel) -> int:
    """Remove all detections/badges from the frame (e.g. clearing false positives).
    Never marks reviewed. Returns how many were removed."""
    n = len(label.badges)
    label.badges = []
    return n


def mark_all_pct(label: FrameLabel, pct: int, *, confirmed: bool = False) -> int:
    """Set EVERY badge to ``pct`` — only when the caller passes ``confirmed=True``
    (the GUI shows an explicit confirmation first). Never marks reviewed. Returns
    the number of badges changed; 0 (a no-op) if not confirmed."""
    if not confirmed:
        return 0
    if pct not in VALID_PCTS:
        raise ValueError(f"pct must be one of {sorted(VALID_PCTS)}")
    for b in label.badges:
        b.pct = int(pct)
    return len(label.badges)


def reset_to_suggestions(label: FrameLabel, scan) -> int:
    """Replace the frame's badges with the detector's current suggestions
    (positions, plus any confidently-classified percentage). Never marks reviewed.
    Returns the number of suggested badges."""
    positions = _positions_from_scan(scan)
    label.badges = [Badge(cx=x, cy=y, pct=p) for x, y, p in positions]
    return len(label.badges)


__all__ = ["accept_all_positions", "remove_all", "mark_all_pct", "reset_to_suggestions"]
