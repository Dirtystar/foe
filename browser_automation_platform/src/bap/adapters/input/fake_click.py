"""A test double for :class:`bap.forge.click.port.ClickPort` (Milestone 6A.1).

Records every ``click_at`` call and never touches the OS. Used everywhere off
Windows and in all unit tests so the controller's "at most one click" guarantee is
directly assertable via :pyattr:`clicks`.
"""

from __future__ import annotations


class FakeClick:
    """Records clicks; performs none. Single-click boundary only."""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click_at(self, screen_x: int, screen_y: int) -> None:
        self.clicks.append((int(screen_x), int(screen_y)))

    @property
    def count(self) -> int:
        return len(self.clicks)


__all__ = ["FakeClick"]
