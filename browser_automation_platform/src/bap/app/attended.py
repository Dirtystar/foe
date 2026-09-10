"""Attended-mode glue: session→tab assignment, the tab provider, gating, and
local persistence of the assignment.

This is composition-layer plumbing: it maps the config's profiles (still the
internal model) to the user-chosen browser tabs and builds the `TabProvider`
that SessionManager uses to adopt them. It stores only tab *metadata* (id,
title, url) — never cookies or credentials (Chromium's persistent profile owns
those).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from bap.core.domain.models import BrowserTab
from bap.core.engine.session_manager import SessionSpec, TabProvider
from bap.core.ports.tab_source_port import TabSourcePort


class UnassignedSessionError(Exception):
    """Raised when a session is started without a tab assigned to it."""


class TabAssignment:
    """Mutable profile_id → chosen BrowserTab map, shared between the GUI (which
    fills it as the user picks) and the tab provider (which reads it at start)."""

    def __init__(self) -> None:
        self._by_profile: dict[str, BrowserTab] = {}

    def assign(self, profile_id: str, tab: BrowserTab) -> None:
        self._by_profile[profile_id] = tab

    def clear(self, profile_id: str) -> None:
        self._by_profile.pop(profile_id, None)

    def get(self, profile_id: str) -> BrowserTab | None:
        return self._by_profile.get(profile_id)

    def as_dict(self) -> dict[str, BrowserTab]:
        return dict(self._by_profile)

    def unassigned(self, profile_ids: list[str]) -> list[str]:
        """Which of these profiles still have no tab — the runtime is blocked
        from starting while this is non-empty."""
        return [pid for pid in profile_ids if pid not in self._by_profile]

    def all_assigned(self, profile_ids: list[str]) -> bool:
        return not self.unassigned(profile_ids)


def make_tab_provider(browser: TabSourcePort, assignment: TabAssignment) -> TabProvider:
    """Build the SessionManager tab provider that adopts the tab the user
    assigned to each profile. Raises `UnassignedSessionError` if a session is
    started without an assignment (a safety net behind the GUI's start gating)."""

    async def provide(spec: SessionSpec):
        tab = assignment.get(spec.profile_id)
        if tab is None:
            raise UnassignedSessionError(
                f"No browser tab assigned to session '{spec.profile_id}'. "
                f"Open the browser, scan tabs, and pick one for every session."
            )
        return await browser.adopt_tab(tab.tab_id)

    return provide


# --- local persistence (metadata only) ---------------------------------------


def save_assignment(path: Path, assignment: TabAssignment) -> None:
    """Persist the assignment as plain JSON (tab id/title/url only)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {pid: asdict(tab) for pid, tab in assignment.as_dict().items()}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_assignment(path: Path) -> TabAssignment:
    """Load a previously saved assignment. A missing/invalid file yields an
    empty assignment (the user just re-picks)."""
    assignment = TabAssignment()
    path = Path(path)
    if not path.exists():
        return assignment
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return assignment
    for pid, tab in (data or {}).items():
        try:
            assignment.assign(pid, BrowserTab(tab_id=tab["tab_id"], title=tab["title"], url=tab["url"]))
        except (KeyError, TypeError):
            continue
    return assignment


__all__ = [
    "TabAssignment",
    "UnassignedSessionError",
    "load_assignment",
    "make_tab_provider",
    "save_assignment",
]
