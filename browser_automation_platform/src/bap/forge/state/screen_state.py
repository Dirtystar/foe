"""UI state model + classifier — "Where am I?" (Milestone A, read-only).

This answers exactly one question about a single screenshot: **which Forge UI state
is on screen right now?** It does **not** decide what to do, perform any automation,
or contain gameplay logic — a future state machine will own transitions and
workflow. Its responsibility ends at a reliable classification with a confidence and
the supporting signals.

Design:

- **Small on purpose.** Only ``GBG_MAP`` and ``PROVINCE_PANEL`` are classified today;
  everything else — and anything uncertain — is ``UNKNOWN``. **No guessing.**
- **Grows naturally.** States are an open enum and detectors live in a registry
  (`detectors.DEFAULT_DETECTORS`), so a new state (City, Battle, Result, Loading,
  Connection Lost, …) is added by registering a detector — the classifier here does
  not change.
- **Fail-safe decision.** A state wins only if its score clears ``min_confidence``
  **and** leads the runner-up by ``min_margin``; otherwise the answer is ``UNKNOWN``.
- **Observable.** The result carries per-state candidate scores, the supporting
  signals, and a human reason, and every classification emits one structured log line.

Read-only: importing or calling this changes no automation, clicking, or gameplay.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("bap.forge.state")

# Decision thresholds (grounded in the measured signal distributions; see the
# milestone report). A candidate must clear the bar AND clearly lead the field.
DEFAULT_MIN_CONFIDENCE = 0.60
DEFAULT_MIN_MARGIN = 0.15


class ScreenState(str, Enum):
    """The UI states this milestone can name. Intentionally small; the enum is the
    single place future states are added (City, GUILD_BATTLEGROUNDS, GUILD_EXPEDITION,
    BATTLE, RESULT, DIALOG, REWARDS, CONNECTION_LOST, UPDATE_REQUIRED, LOADING,
    UNEXPECTED_POPUP, …). Until a detector exists for a state, screens of that kind
    correctly fall back to ``UNKNOWN`` — never a guess."""

    GBG_MAP = "GBG_MAP"
    PROVINCE_PANEL = "PROVINCE_PANEL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class StateSignal:
    """One piece of supporting evidence a detector observed (for transparency/logs).
    ``state`` tags which state's detector produced it."""

    state: ScreenState
    name: str
    value: object
    detail: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state.value, "name": self.name, "value": self.value,
                "detail": self.detail}


@dataclass(frozen=True)
class StateEvidence:
    """A detector's verdict for its own state: a score in [0, 1] plus the signals it
    based that score on. A detector never claims another state — it only scores its
    own and explains why."""

    score: float
    signals: list[StateSignal] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class ScreenClassification:
    """The classifier's answer to "where am I?"."""

    state: ScreenState
    confidence: float
    signals: list[StateSignal]
    reason: str
    candidates: dict[ScreenState, float]   # per-state score, for observability

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "candidates": {s.value: round(float(v), 4) for s, v in self.candidates.items()},
            "signals": [s.to_dict() for s in self.signals],
        }


def decide(candidates: dict[ScreenState, float], *,
           min_confidence: float = DEFAULT_MIN_CONFIDENCE,
           min_margin: float = DEFAULT_MIN_MARGIN) -> tuple[ScreenState, float, str]:
    """Pure decision: pick the top-scoring state iff it clears ``min_confidence`` and
    leads the runner-up by ``min_margin``; otherwise ``UNKNOWN``. No guessing."""
    scored = {s: float(v) for s, v in candidates.items() if s is not ScreenState.UNKNOWN}
    if not scored:
        return ScreenState.UNKNOWN, 0.0, "no state detectors produced a score — UNKNOWN"
    best_state = max(scored, key=lambda s: scored[s])
    best = scored[best_state]
    runner_up = max((v for s, v in scored.items() if s is not best_state), default=0.0)
    margin = best - runner_up
    if best < min_confidence:
        return (ScreenState.UNKNOWN, best,
                f"top candidate {best_state.value} scored {best:.2f} < {min_confidence:.2f} — UNKNOWN")
    if margin < min_margin:
        return (ScreenState.UNKNOWN, best,
                f"{best_state.value} {best:.2f} did not lead the field by {min_margin:.2f} "
                f"(margin {margin:.2f}) — ambiguous, UNKNOWN")
    return (best_state, best,
            f"{best_state.value} scored {best:.2f} ≥ {min_confidence:.2f} and led by {margin:.2f}")


def classify_screen(image, *, detectors=None, context=None,
                    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
                    min_margin: float = DEFAULT_MIN_MARGIN) -> ScreenClassification:
    """Classify the current screen from one BGR screenshot. Read-only.

    Runs every registered state detector, collects a score + signals per state, and
    applies the fail-safe :func:`decide` rule. Any detector that errors contributes a
    score of 0 (a broken detector can never *win* a state — it can only abstain).
    """
    if detectors is None:
        from bap.forge.state.detectors import DEFAULT_DETECTORS, DetectContext

        detectors = DEFAULT_DETECTORS
        context = context or DetectContext()

    candidates: dict[ScreenState, float] = {}
    signals: list[StateSignal] = []
    if image is None:
        result = ScreenClassification(
            ScreenState.UNKNOWN, 0.0, [], "no image provided — UNKNOWN",
            {ScreenState.GBG_MAP: 0.0, ScreenState.PROVINCE_PANEL: 0.0})
        logger.info("screen_state", extra={"screen_state": result.to_dict()})
        return result

    for state, detector in detectors.items():
        try:
            ev = detector(image, context)
            candidates[state] = max(0.0, min(1.0, float(ev.score)))
            signals.extend(ev.signals)
        except Exception:  # a broken detector abstains; it never wins
            logger.warning("state detector %s failed", state.value, exc_info=True)
            candidates[state] = 0.0

    state, confidence, reason = decide(
        candidates, min_confidence=min_confidence, min_margin=min_margin)
    result = ScreenClassification(state, confidence, signals, reason, candidates)
    logger.info("screen_state", extra={"screen_state": result.to_dict()})
    return result


__all__ = [
    "ScreenState", "StateSignal", "StateEvidence", "ScreenClassification",
    "classify_screen", "decide",
    "DEFAULT_MIN_CONFIDENCE", "DEFAULT_MIN_MARGIN",
]
