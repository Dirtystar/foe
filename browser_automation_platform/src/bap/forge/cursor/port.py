"""The intentionally tiny cursor-preview boundary (Milestone 5A).

M5A introduces the **first real output action**: a manual, one-shot cursor MOVE to
the validated would-click point. It must be **impossible** for this milestone to
click, type, drag, or scroll. That guarantee is enforced structurally here — the
port exposes exactly one method, ``move_to``, and nothing else. There is no
click / mouse-down / mouse-up / double-click / drag / scroll / key method to call,
so no amount of wiring downstream can perform one.

This is deliberately **not** part of the generic action engine
(`ActionHandlerPort`) — the Forge product must never gain a general-purpose input
API. Any real implementation (e.g. a Windows ``SetCursorPos`` adapter) implements
only this method.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CursorPreviewPort(Protocol):
    """Move the OS cursor to an absolute screen point. **Movement only** — this
    port cannot click, press, drag, scroll, or type, by construction."""

    def move_to(self, screen_x: int, screen_y: int) -> None:
        """Move the cursor once to the physical screen pixel ``(screen_x,
        screen_y)``. No button state changes. Never clicks."""
        ...


#: The set of method names this milestone forbids on any cursor adapter. Tests
#: assert none of these exist, so a future edit that adds one fails loudly.
FORBIDDEN_INPUT_METHODS = (
    "click", "double_click", "mouse_down", "mouse_up", "press", "release",
    "drag", "scroll", "type", "type_text", "key_down", "key_up", "send_keys",
)


__all__ = ["CursorPreviewPort", "FORBIDDEN_INPUT_METHODS"]
