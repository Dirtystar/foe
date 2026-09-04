"""Live Data Collection (Milestone 5D) — OBSERVE-ONLY.

A fast operator workflow for collecting, reviewing, and validating live Chrome
badge data across multiple Worlds. Everything here is measurement / data plumbing:
it takes a screenshot the caller already produced (read-only), runs the EXISTING
detector/classifier for *suggestions only*, and files the frame into the canonical
reviewed dataset with provenance. Nothing clicks, moves the cursor, types, drives
a browser, changes any detector/classifier threshold, or retrains a model.
"""

from bap.forge.collection.session import (
    CollectionSession,
    active_session,
    list_sessions,
    load_session,
    start_session,
)

__all__ = [
    "CollectionSession", "start_session", "load_session", "list_sessions",
    "active_session",
]
