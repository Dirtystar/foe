"""The intentionally tiny click boundary (Milestone 6A.1).

M6A.1 introduces the **first real click**: one operator-confirmed left click on the
validated map badge, used to open the province/detail panel for an independent
second reading of the percentage. It must be **impossible** for this port to
double-click, drag, scroll, hold, or type — exactly as the M5A cursor port is
movement-only. That guarantee is enforced *structurally*: this port exposes exactly
one method, ``click_at``, and nothing else.

This is a **separate sibling** of :class:`bap.forge.cursor.port.CursorPreviewPort`.
Do **not** add ``click_at`` (or any click method) to the cursor port — the cursor
port stays movement-only, and this port stays single-click-only. No amount of wiring
can turn either into a general-purpose input API.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ClickPort(Protocol):
    """Perform exactly one left click at an absolute physical screen point.

    **Single left click only** — this port cannot double-click, right-click,
    middle-click, drag, scroll, hold a button, or type, by construction."""

    def click_at(self, screen_x: int, screen_y: int) -> None:
        """Left-click once at the physical screen pixel ``(screen_x, screen_y)``:
        button down then up at the same point. No double-click, no drag, no hold."""
        ...


#: Method names forbidden on any click adapter. Tests assert none of these exist,
#: so a future edit that adds one fails loudly.
FORBIDDEN_INPUT_METHODS = (
    "double_click", "right_click", "middle_click", "mouse_down", "mouse_up",
    "press", "release", "hold", "drag", "scroll", "type", "type_text",
    "key_down", "key_up", "send_keys",
)


__all__ = ["ClickPort", "FORBIDDEN_INPUT_METHODS"]
