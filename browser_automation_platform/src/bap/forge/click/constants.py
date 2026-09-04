"""Tunable bounds for the M6A.1 Open & Verify flow (single manual click).

All values are conservative and fail-safe: exceeding any of them stops the flow
rather than clicking again or guessing. Nothing here loops or retries.
"""

from __future__ import annotations

# The would-click target must come from a scan no older than this at click time.
# Tighter than the cursor-preview move bar (5 s) because a click is destructive.
MAX_CLICK_AGE_S: float = 2.0

# After the single click, poll for the province/detail panel for at most this long
# before giving up (STOP — never a second click).
PANEL_WAIT_TIMEOUT_S: float = 3.0

# Interval between panel-appearance polls during the wait.
PANEL_POLL_INTERVAL_S: float = 0.25

# The physical cursor must be within this many pixels of the target after the
# move, or the click is blocked (the operator or something moved it).
CURSOR_TOLERANCE_PX: int = 3

__all__ = [
    "MAX_CLICK_AGE_S",
    "PANEL_WAIT_TIMEOUT_S",
    "PANEL_POLL_INTERVAL_S",
    "CURSOR_TOLERANCE_PX",
]
