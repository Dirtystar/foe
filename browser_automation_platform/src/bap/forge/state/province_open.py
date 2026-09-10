"""Verify that opening a province produced the expected UI state (Milestone, read-only).

After the single click that opens a province (M6A.1), this answers one honest
question about the resulting screenshot: **did we land on `PROVINCE_PANEL`?** It
reuses the Milestone-A classifier (`classify_screen`) and reports exactly what it
observed — `PROVINCE_PANEL`, `UNKNOWN`, `GBG_MAP`, or whatever else — with the
confidence and the classifier's signals. It never retries, never guesses, and never
infers intent.

When the observation is **not** `PROVINCE_PANEL`, that is valuable product feedback,
not a failure: :func:`save_unknown_capture` writes the screenshot, the classifier
output, and the execution context to a folder so it can be reviewed and, if useful,
added to the dataset later. This is deliberately a couple of **plain helper
functions**, not a reusable "capture store" abstraction — we do not yet know enough
about future collection needs to justify one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bap.forge.state.screen_state import (
    ScreenClassification,
    ScreenState,
    classify_screen,
)

logger = logging.getLogger("bap.forge.state")

EXPECTED_STATE = ScreenState.PROVINCE_PANEL


@dataclass(frozen=True)
class ProvinceOpenObservation:
    """An honest record of one province-open attempt's result. ``observed`` is
    whatever the classifier actually saw — it is never reinterpreted."""

    attempted: bool
    expected: ScreenState
    observed: ScreenState
    confidence: float
    classification: ScreenClassification
    captured_path: str | None
    reason: str

    @property
    def confirmed(self) -> bool:
        """True only when the observed state is exactly the expected one."""
        return self.observed is self.expected

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "expected": self.expected.value,
            "observed": self.observed.value,
            "confirmed": self.confirmed,
            "confidence": round(float(self.confidence), 4),
            "captured_path": self.captured_path,
            "reason": self.reason,
            "classification": self.classification.to_dict(),
        }


def _save_capture(capture_dir, image, classification: ScreenClassification,
                  exec_context: dict | None, *, prefix: str) -> str | None:
    """Write a screenshot + classifier output + execution context to a timestamped
    ``<prefix>_<ts>`` folder. Best-effort: a write failure returns None and never
    raises. Intentionally a plain function, not a store abstraction."""
    if capture_dir is None:
        return None
    try:
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        import cv2

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        out = Path(capture_dir) / f"{prefix}_{ts}"
        out.mkdir(parents=True, exist_ok=True)
        if image is not None:
            cv2.imwrite(str(out / "screen.png"), image)
        (out / "classification.json").write_text(
            json.dumps(classification.to_dict(), indent=2), encoding="utf-8")
        (out / "context.json").write_text(json.dumps({
            "observed_state": classification.state.value,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **(exec_context or {}),
        }, indent=2), encoding="utf-8")
        return str(out)
    except Exception:  # never let a best-effort capture affect the flow
        logger.warning("failed to save %s-state capture", prefix, exc_info=True)
        return None


def save_unknown_capture(capture_dir, image, classification: ScreenClassification,
                         exec_context: dict | None) -> str | None:
    """Save a not-as-expected observation (screenshot + classifier output + context)
    to an ``unknown_<ts>`` folder for later review. Best-effort; returns None on
    failure. Thin wrapper over :func:`_save_capture`."""
    return _save_capture(capture_dir, image, classification, exec_context,
                         prefix="unknown")


def save_confirmed_capture(capture_dir, image, classification: ScreenClassification,
                           exec_context: dict | None) -> str | None:
    """Save a **confirmed** ``PROVINCE_PANEL`` observation to a ``panel_<ts>`` folder.

    The success frame is the exact screenshot the dataset is missing — capturing it
    is how the first real open grows the panel dataset the weakening-reader needs.
    Best-effort; returns None on failure. Thin wrapper over :func:`_save_capture`."""
    return _save_capture(capture_dir, image, classification, exec_context,
                         prefix="panel")


def observe_province_open(after_image, *, detectors=None, detect_context=None,
                          capture_dir=None, capture_confirmed: bool = False,
                          exec_context: dict | None = None) -> ProvinceOpenObservation:
    """Classify the post-click screenshot and report the observed UI state vs the
    expected `PROVINCE_PANEL`. On any other observed state, save the screenshot +
    signals + context (when ``capture_dir`` is given). When ``capture_confirmed`` is
    set, a confirmed `PROVINCE_PANEL` is *also* saved — the success frame is the panel
    screenshot the dataset lacks. Honest and read-only: no click, no next action.
    """
    clf = classify_screen(after_image, detectors=detectors, context=detect_context)
    observed = clf.state
    captured = None
    if observed is not EXPECTED_STATE:
        captured = save_unknown_capture(capture_dir, after_image, clf, exec_context)
    elif capture_confirmed:
        captured = save_confirmed_capture(capture_dir, after_image, clf, exec_context)
    reason = (f"expected {EXPECTED_STATE.value}; observed {observed.value} "
              f"(confidence {clf.confidence:.2f})")
    obs = ProvinceOpenObservation(
        attempted=True, expected=EXPECTED_STATE, observed=observed,
        confidence=clf.confidence, classification=clf, captured_path=captured,
        reason=reason)
    logger.info("province_open_observation", extra={"province_open": obs.to_dict()})
    return obs


__all__ = [
    "ProvinceOpenObservation", "observe_province_open", "save_unknown_capture",
    "save_confirmed_capture", "EXPECTED_STATE",
]
