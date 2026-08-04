"""Manual one-shot cursor **preview** (Milestone 5A) — move only, never click.

The first real output action in the product: on an explicit operator confirmation,
the OS cursor moves once to the validated would-click point. It is impossible for
this package to click, type, drag, or scroll — the only output method anywhere is
``CursorPreviewPort.move_to``. Everything else here is a strict manual gate, an
explicit image→screen coordinate contract, and an append-only audit trail.
"""

from __future__ import annotations

from bap.forge.cursor.audit import CursorPreviewAudit, EVENT_CURSOR_PREVIEW_ONLY
from bap.forge.cursor.controller import CursorPreviewController, MoveResult
from bap.forge.cursor.geometry import CoordinateTrace, WindowGeometry, image_to_screen
from bap.forge.cursor.port import CursorPreviewPort
from bap.forge.cursor.preview import (
    DEFAULT_MAX_SCAN_AGE_S,
    PreviewDecision,
    PreviewRequest,
    evaluate_preview,
)

__all__ = [
    "CursorPreviewPort",
    "CursorPreviewController",
    "MoveResult",
    "CursorPreviewAudit",
    "EVENT_CURSOR_PREVIEW_ONLY",
    "WindowGeometry",
    "CoordinateTrace",
    "image_to_screen",
    "PreviewRequest",
    "PreviewDecision",
    "evaluate_preview",
    "DEFAULT_MAX_SCAN_AGE_S",
]
