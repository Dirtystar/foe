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
import math
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


def auto_labels(layout, *, columns: int = 4, rows: int = 4) -> dict[int, str]:
    """Positional grid labels (``A1``, ``C3``, …) from the map asset's flag positions —
    columns left→right as letters, rows top→bottom as numbers, over the bounding box of the
    flags themselves so the grid is tight on the actual map.

    The 4×4 default mirrors the shape the guild already uses out loud (``A1X``, ``D4A``,
    ``C3Y``: sector letter, sector number, then a per-province letter), so a generated label
    lands in the right sector and only the trailing letter is left to fill in by hand.

    The GBG flags are hand-placed, not a lattice, so this is still a *hint*, not a naming
    standard. Provinces sharing a cell get a distinguishing letter (``C3``, ``C3B``, ``C3C``)
    so a label is always unique. ``layout`` is a
    :class:`~bap.forge.gbg_data.map_layout.MapLayout` (or anything with ``flags``); no layout
    → ``{}``.
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
        out[pid] = base if n == 0 else f"{base}{_ALPHABET[min(n, 25)]}"
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




# --------------------------------------------------------------------- hex rings

#: A GBG map is a centred hexagon: 1 + 6 + 12 + 18 + … provinces. These are the totals that
#: identify one ("centred hexagonal numbers"), and the ring sizes that follow from them.
def _hex_ring_sizes(count: int) -> list[int] | None:
    sizes, total = [1], 1
    while total < count:
        sizes.append(6 * len(sizes))
        total += sizes[-1]
    return sizes if total == count else None


def hex_cells(layout, *, y_scale: float = 1.4, sector_offset: float = 40.0):
    """Decompose a map into ``{province id: (ring, sector, index within the cell)}``.

    The game names provinces by **position, not by a grid**: the number is the ring out from
    the centre and the letter is the compass sector — and a GBG map really is a centred
    hexagon, so ring *r* holds exactly *r* provinces in each of the six sectors. Verified
    against a live 61-province map: every one of the 24 (ring, sector) cells came out at
    exactly the expected size.

    ``y_scale`` undoes the isometric squash of the drawn map; ``sector_offset`` rotates the
    sector boundaries. Returns ``{}`` when the map is not a centred hexagon.
    """
    flags = dict(getattr(layout, "flags", None) or {})
    sizes = _hex_ring_sizes(len(flags)) if flags else None
    if not sizes:
        return {}
    # The centre is the middle *province*, not the centroid of the cloud: an asymmetric map
    # edge drags the centroid off, and every ring is then measured from the wrong origin.
    gx = sum(x for x, _ in flags.values()) / len(flags)
    gy = sum(y for _, y in flags.values()) / len(flags)
    cx, cy = min(flags.values(), key=lambda p: math.hypot(p[0] - gx, p[1] - gy))
    polar = {}
    for pid, (x, y) in flags.items():
        dx, dy = x - cx, (y - cy) * y_scale
        polar[pid] = (math.hypot(dx, dy),
                      (math.degrees(math.atan2(-dy, dx)) + 360) % 360)
    order = sorted(polar, key=lambda p: polar[p][0])
    out: dict[int, tuple[int, int, int]] = {}
    seen: dict[tuple[int, int], int] = {}
    start = 0
    for ring, size in enumerate(sizes):
        band = order[start:start + size]
        start += size
        if ring == 0:
            for pid in band:
                out[pid] = (0, 0, 0)
            continue
        # inside a ring, walk the sectors by angle so the index is stable and positional
        for pid in sorted(band, key=lambda p: (polar[p][1] - sector_offset) % 360):
            sector = int(((polar[pid][1] - sector_offset) % 360) // 60)
            idx = seen.get((ring, sector), 0)
            seen[(ring, sector)] = idx + 1
            out[pid] = (ring, sector, idx)
    return out


def ring_labels(layout, *, ring_base: int = 1, sector_origin: int = 0, clockwise: bool = False,
                centre_label: str = "", **cells_kw) -> dict[int, str]:
    """Positional labels in the game's own shape — ``F5D``: sector letter, ring number, and a
    letter for which of the cell's provinces it is.

    The four knobs are exactly the things a map cannot tell us and only a handful of known
    labels can: where sector ``A`` starts, which way the letters run, whether the centre
    counts as ring 1, and what the centre itself is called. :func:`fit_ring_labels` picks them.
    """
    cells = hex_cells(layout, **cells_kw)
    if not cells:
        return {}
    out: dict[int, str] = {}
    for pid, (ring, sector, idx) in cells.items():
        if ring == 0:
            if centre_label:
                out[pid] = centre_label
            continue
        s = (sector_origin - sector) % 6 if clockwise else (sector - sector_origin) % 6
        out[pid] = f"{_ALPHABET[s]}{ring + ring_base}{_ALPHABET[idx]}"
    return out


def fit_ring_labels(layout, known: dict[int, str], **cells_kw):
    """Find the knob settings that reproduce ``known`` (province id → the label the guild
    reads off the map), and return ``(labels_for_every_province, settings, matched, total)``.

    A dozen known labels pin the scheme down completely, which is the difference between
    typing sixty names and typing none.
    """
    known = {int(k): str(v).strip().upper() for k, v in known.items() if str(v).strip()}
    best = None
    for ring_base in (0, 1):
        for origin in range(6):
            for clockwise in (False, True):
                labels = ring_labels(layout, ring_base=ring_base, sector_origin=origin,
                                     clockwise=clockwise, **cells_kw)
                hits = sum(1 for pid, name in known.items() if labels.get(pid) == name)
                settings = {"ring_base": ring_base, "sector_origin": origin,
                            "clockwise": clockwise}
                if best is None or hits > best[2]:
                    best = (labels, settings, hits)
    labels, settings, hits = best
    return labels, settings, hits, len(known)


__all__ = ["LabelBook", "auto_labels", "load_label_file", "hex_cells",
           "ring_labels", "fit_ring_labels"]
