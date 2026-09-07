"""Province id → the coordinate the guild actually says out loud ("A1X").

The game's own data carries **no province names** — a province is just an id (0…59) plus a
flag position in the static map asset. Every human name for a sector is therefore a guild
convention, so this module resolves a label in three steps:

1. an explicit mapping the guild writes once per map (``province_labels.<map>.json``),
2. otherwise an auto grid label derived from the flag positions (``B3`` — columns left→right
   as letters, rows top→bottom as numbers), so an unnamed province is still identifiable,
3. otherwise ``#<id>``.

Step 2 also exists to make step 1 cheap: ``bap-alert labels`` prints the whole map as a grid
so the guild can fill in its own names next to a position it recognises.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path

_ALPHABET = string.ascii_uppercase


def load_label_file(path) -> dict[int, str]:
    """Read a labels JSON: either ``{"12": "A1X", …}`` or ``{"labels": {…}}`` (the second
    form may also carry ``map_id``/comments). Unreadable or empty → ``{}``."""
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(obj, dict) and isinstance(obj.get("labels"), dict):
        obj = obj["labels"]
    if not isinstance(obj, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in obj.items():
        try:
            pid = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, str) and v.strip():
            out[pid] = v.strip()
    return out


def _cell(value: float, low: float, high: float, count: int) -> int:
    """Which of ``count`` equal bands ``value`` falls into (clamped)."""
    span = high - low
    if span <= 0:
        return 0
    return min(count - 1, max(0, int((value - low) / span * count)))


def _column_name(i: int) -> str:
    """0→A … 25→Z, 26→AA (a 60-province map never gets that far, but never crash)."""
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = _ALPHABET[r] + name
    return name


def auto_labels(layout, *, columns: int = 12, rows: int = 10) -> dict[int, str]:
    """Positional grid labels (``A1``, ``F7``, …) from the map asset's flag positions —
    columns left→right as letters, rows top→bottom as numbers, over the bounding box of the
    flags themselves so the grid is tight on the actual map.

    The GBG flags are hand-placed, not a lattice, so this is a *hint*, not a naming standard:
    it exists to make the labels template recognisable and to keep unnamed provinces
    identifiable. Two provinces sharing a cell get a suffix (``F7``, ``F7b``) so a label is
    always unique. ``layout`` is a :class:`~bap.forge.gbg_data.map_layout.MapLayout` (or
    anything with ``flags``); no layout → ``{}``.
    """
    flags = dict(getattr(layout, "flags", None) or {})
    if not flags:
        return {}
    xs = [x for x, _ in flags.values()]
    ys = [y for _, y in flags.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out: dict[int, str] = {}
    used: dict[str, int] = {}
    for pid in sorted(flags):                       # deterministic order → stable suffixes
        x, y = flags[pid]
        base = f"{_column_name(_cell(x, x0, x1, columns))}{_cell(y, y0, y1, rows) + 1}"
        n = used.get(base, 0)
        used[base] = n + 1
        out[pid] = base if n == 0 else f"{base}{_ALPHABET[min(n, 25)].lower()}"
    return out


@dataclass
class LabelBook:
    """Resolves a province id to the best available label (guild name → grid → ``#id``)."""

    overrides: dict[int, str]
    auto: dict[int, str]

    @classmethod
    def build(cls, *, path=None, layout=None) -> "LabelBook":
        return cls(overrides=load_label_file(path) if path else {},
                   auto=auto_labels(layout) if layout is not None else {})

    def with_layout(self, layout) -> "LabelBook":
        """Same overrides, auto labels refreshed from a (newly seen) map layout."""
        return LabelBook(overrides=dict(self.overrides), auto=auto_labels(layout))

    def named_ids(self) -> set[int]:
        """Province ids the guild has explicitly named — the natural 'we care about these'
        set for ``--scope labeled``."""
        return set(self.overrides)

    def label(self, province_id: int) -> str:
        return (self.overrides.get(province_id)
                or self.auto.get(province_id)
                or f"#{province_id}")


__all__ = ["LabelBook", "auto_labels", "load_label_file"]
