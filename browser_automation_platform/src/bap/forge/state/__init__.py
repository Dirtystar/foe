"""UI state detection — "Where am I?" (Milestone A, read-only).

Answers which Forge UI state a screenshot shows (`GBG_MAP`, `PROVINCE_PANEL`, or a
fail-safe `UNKNOWN`), with a confidence and the supporting signals. It contains **no**
automation, transition, or gameplay logic — a future state machine will consume this
to decide "what should I do next?". The state enum and the detector registry are the
single, well-defined places new states grow.
"""

from __future__ import annotations

from bap.forge.state.screen_state import (
    ScreenClassification,
    ScreenState,
    StateEvidence,
    StateSignal,
    classify_screen,
    decide,
)

__all__ = [
    "ScreenState", "ScreenClassification", "StateSignal", "StateEvidence",
    "classify_screen", "decide",
]
