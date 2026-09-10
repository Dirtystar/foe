"""A recording fake cursor for tests (Milestone 5A).

Implements the whole `CursorPreviewPort` — a single `move_to` — and records every
move so tests can assert exactly one move happened at the expected point. It has
**no** click/keyboard method, by construction, so tests can also assert the port
surface never grew one.
"""

from __future__ import annotations


class FakeCursorPreview:
    """Records `move_to` calls. Nothing else — no click/press/drag/scroll/type."""

    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []

    def move_to(self, screen_x: int, screen_y: int) -> None:
        self.moves.append((int(screen_x), int(screen_y)))

    @property
    def move_count(self) -> int:
        return len(self.moves)

    @property
    def last(self) -> tuple[int, int] | None:
        return self.moves[-1] if self.moves else None


__all__ = ["FakeCursorPreview"]
