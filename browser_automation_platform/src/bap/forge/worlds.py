"""Persistent Forge Worlds — the primary unit the user manages.

A **World** is one Forge account/server the assistant operates. It carries two
kinds of identity, deliberately kept apart:

  - **alias** — the user-facing name ("Main", "Farm", "H"). What the user reads
    and edits. Must be unique within the store.
  - **hostname** — the durable *technical* identity (e.g. ``cz8.forgeofempires.com``).
    This is what a browser tab is matched back to on reattachment. It never
    changes for a given server, unlike a browser tab id which is regenerated
    every session and must never be used as identity.

Per-world settings (click cadence, max weakening, allowed badge percentages,
future strategy options) live on the World and are persisted automatically, so
the next launch restores everything — only the live browser tabs need
reattaching, which happens by hostname.

This module is pure domain + JSON persistence: no Qt, no Playwright, no engine
imports beyond the plain `BrowserTab` data model. That keeps it trivially
testable and safe to load anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

from bap.core.domain.models import BrowserTab

# The five Guild Battlegrounds weakening levels. Fixed by the game.
BADGE_PCTS: tuple[int, ...] = (20, 40, 60, 80, 100)

_FORGE_HOST_SUFFIX = "forgeofempires.com"


class WorldError(ValueError):
    """Invalid World definition or store operation."""


def normalize_hostname(url_or_host: str) -> str:
    """Reduce a tab URL (or a bare host) to the lowercase Forge hostname used as
    durable identity, e.g. ``https://cz8.forgeofempires.com/game/index`` ->
    ``cz8.forgeofempires.com``. Returns "" when no host can be parsed."""
    if not url_or_host:
        return ""
    text = url_or_host.strip().lower()
    host = urlparse(text).hostname if "//" in text else urlparse("//" + text).hostname
    if not host or " " in host or "." not in host:
        # A real host has no spaces and is dotted; reject bare words like a
        # stray "not a url" that urlparse would otherwise echo back as a host.
        return ""
    return host


def is_forge_hostname(host: str) -> bool:
    host = normalize_hostname(host)
    return host == _FORGE_HOST_SUFFIX or host.endswith("." + _FORGE_HOST_SUFFIX)


@dataclass(frozen=True)
class World:
    """One Forge account/server the assistant operates. Immutable; edits produce
    a new World via :meth:`with_changes` so the store controls persistence."""

    alias: str
    hostname: str
    interval_ms: int = 1000
    max_weakening_pct: int = 100
    allowed_pcts: tuple[int, ...] = BADGE_PCTS
    strategy: dict = field(default_factory=dict)
    # Display/recognition metadata captured from the scanned tab (NOT identity —
    # hostname is the durable key). Helps the user recognise a world and lets the
    # Add-World form prefill without any manual typing.
    title: str = ""
    last_url: str = ""

    def __post_init__(self) -> None:
        alias = self.alias.strip()
        if not alias:
            raise WorldError("World alias must be a non-empty name.")
        object.__setattr__(self, "alias", alias)

        host = normalize_hostname(self.hostname)
        if not host:
            raise WorldError(f"World '{alias}': a Forge server hostname is required.")
        if not is_forge_hostname(host):
            raise WorldError(
                f"World '{alias}': '{self.hostname}' is not a Forge server "
                f"(expected a *.{_FORGE_HOST_SUFFIX} host)."
            )
        object.__setattr__(self, "hostname", host)

        if self.interval_ms <= 0:
            raise WorldError(f"World '{alias}': interval_ms must be > 0.")
        if not 0 <= self.max_weakening_pct <= 100:
            raise WorldError(f"World '{alias}': max_weakening_pct must be in 0..100.")

        pcts = tuple(sorted({int(p) for p in self.allowed_pcts}))
        bad = [p for p in pcts if p not in BADGE_PCTS]
        if bad:
            raise WorldError(
                f"World '{alias}': allowed_pcts {bad} not in {list(BADGE_PCTS)}."
            )
        object.__setattr__(self, "allowed_pcts", pcts)

    def with_changes(self, **changes) -> "World":
        """Return a validated copy with the given fields replaced."""
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "hostname": self.hostname,
            "interval_ms": self.interval_ms,
            "max_weakening_pct": self.max_weakening_pct,
            "allowed_pcts": list(self.allowed_pcts),
            "strategy": dict(self.strategy),
            "title": self.title,
            "last_url": self.last_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        try:
            return cls(
                alias=data["alias"],
                hostname=data["hostname"],
                interval_ms=int(data.get("interval_ms", 1000)),
                max_weakening_pct=int(data.get("max_weakening_pct", 100)),
                allowed_pcts=tuple(data.get("allowed_pcts", BADGE_PCTS)),
                strategy=dict(data.get("strategy", {})),
                title=str(data.get("title", "")),
                last_url=str(data.get("last_url", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorldError(f"Invalid world record: {exc}") from exc


class WorldStore:
    """An ordered collection of Worlds, keyed by alias, persisted to JSON.

    Mutations (add/update/remove) auto-save when the store was created with a
    path, so world settings survive across launches without an explicit save
    step. Aliases and hostnames are both unique — the hostname because it is the
    reattachment key, the alias because it is how the user refers to a world.
    """

    def __init__(self, path: Path | str | None = None, worlds: Iterable[World] = ()):
        self._path = Path(path) if path is not None else None
        self._worlds: dict[str, World] = {}
        for world in worlds:
            self._insert(world)

    # --- reads --------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def __len__(self) -> int:
        return len(self._worlds)

    def list(self) -> list[World]:
        """Worlds in insertion order."""
        return list(self._worlds.values())

    def get(self, alias: str) -> World | None:
        return self._worlds.get(alias.strip())

    def aliases(self) -> list[str]:
        return list(self._worlds)

    # --- mutations (auto-saving) -------------------------------------------

    def add(self, world: World) -> None:
        if world.alias in self._worlds:
            raise WorldError(f"A world named '{world.alias}' already exists.")
        self._check_hostname_free(world.hostname, ignore_alias=None)
        self._worlds[world.alias] = world
        self.save()

    def update(self, alias: str, world: World) -> None:
        """Replace the world stored under `alias` (its alias may change)."""
        alias = alias.strip()
        if alias not in self._worlds:
            raise WorldError(f"No world named '{alias}'.")
        if world.alias != alias and world.alias in self._worlds:
            raise WorldError(f"A world named '{world.alias}' already exists.")
        self._check_hostname_free(world.hostname, ignore_alias=alias)
        # Preserve order while allowing an alias rename.
        rebuilt: dict[str, World] = {}
        for key, existing in self._worlds.items():
            if key == alias:
                rebuilt[world.alias] = world
            else:
                rebuilt[key] = existing
        self._worlds = rebuilt
        self.save()

    def remove(self, alias: str) -> None:
        alias = alias.strip()
        if alias not in self._worlds:
            raise WorldError(f"No world named '{alias}'.")
        del self._worlds[alias]
        self.save()

    # --- hostname-based tab reattachment -----------------------------------

    def match_tabs(self, tabs: Sequence[BrowserTab]) -> dict[str, BrowserTab]:
        """Map each world (by alias) to an open tab whose URL hostname equals the
        world's hostname. Tab ids are ignored entirely — matching is by durable
        Forge hostname, so it survives Chromium regenerating tab ids across
        launches. A world with no matching open tab is simply absent from the
        result (the user assigns it manually as a fallback)."""
        by_host: dict[str, BrowserTab] = {}
        for tab in tabs:
            host = normalize_hostname(tab.url)
            # First tab wins for a given host (stable, deterministic).
            by_host.setdefault(host, tab)
        matches: dict[str, BrowserTab] = {}
        for world in self._worlds.values():
            tab = by_host.get(world.hostname)
            if tab is not None:
                matches[world.alias] = tab
        return matches

    # --- persistence --------------------------------------------------------

    def save(self) -> None:
        """Write the store to its JSON path (no-op when path-less, e.g. tests).
        Written atomically via a temp file so a crash mid-write cannot corrupt
        an existing store."""
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "worlds": [w.to_dict() for w in self._worlds.values()]}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @classmethod
    def load(cls, path: Path | str) -> "WorldStore":
        """Load a store from JSON. A missing file yields an empty store bound to
        that path (so the first add() creates it). A corrupt/invalid record is
        skipped rather than crashing the app — the user re-adds the world."""
        path = Path(path)
        store = cls(path=path)
        if not path.exists():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return store
        for record in (data or {}).get("worlds", []):
            try:
                store._insert(World.from_dict(record))
            except WorldError:
                continue  # skip a bad record, keep the rest
        return store

    # --- internals ----------------------------------------------------------

    def _insert(self, world: World) -> None:
        """Add without saving or raising on a duplicate hostname (used by load,
        which must tolerate a legacy file); alias collisions still overwrite by
        last-wins to keep the map consistent."""
        self._worlds[world.alias] = world

    def _check_hostname_free(self, hostname: str, *, ignore_alias: str | None) -> None:
        for alias, world in self._worlds.items():
            if alias == ignore_alias:
                continue
            if world.hostname == hostname:
                raise WorldError(
                    f"Hostname '{hostname}' is already used by world '{alias}'."
                )


__all__ = [
    "BADGE_PCTS",
    "World",
    "WorldError",
    "WorldStore",
    "is_forge_hostname",
    "normalize_hostname",
]
