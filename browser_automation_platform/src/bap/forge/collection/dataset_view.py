"""Read-only views over the collected data (Milestone 5D): the capture queue,
canonical dataset statistics, shortage hints, target progress, and active-learning
priority. Pure reads — nothing here labels, captures, retrains, or clicks.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from bap.forge.collection.capture import provenance_for
from bap.forge.dataset_store import FRAMES_DIRNAME, LABELS_NAME, reviewed_dataset_dir
from bap.forge.labeling.model import VALID_PCTS, LabelStore

CLASSES = [20, 40, 60, 80, 100]
LIVE_SOURCES = {"live", "snapshot", "live_collection"}


# --------------------------------------------------------------------------- #
# Capture queue                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class QueueEntry:
    frame: str
    path: str
    world: str | None
    timestamp: str | None
    capture_w: int | None
    capture_h: int | None
    detected: int
    classified: int
    unknown: int
    reviewed: bool
    negative: bool           # reviewed AND zero badges
    review_state: str        # "reviewed" | "reviewed_negative" | "pending"
    duplicate: bool
    session_id: str | None
    source: str
    per_class: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def _resolution(w, h) -> str | None:
    return f"{w}x{h}" if w and h else None


def frame_rows(dataset_dir=None) -> list[QueueEntry]:
    """Every frame in the canonical dataset as a queue entry (labels + provenance).
    Duplicate images are flagged by content hash (none should survive dedup, but
    the queue reports the condition rather than hiding it)."""
    d = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()
    frames_dir = d / FRAMES_DIRNAME
    if not frames_dir.is_dir():
        return []
    store = LabelStore.load(d / LABELS_NAME) if (d / LABELS_NAME).exists() else LabelStore()
    md5s: dict[str, list[str]] = defaultdict(list)
    files = sorted(p.name for p in frames_dir.glob("*.png"))
    for name in files:
        md5s[hashlib.md5((frames_dir / name).read_bytes()).hexdigest()].append(name)
    dup_names = {n for group in md5s.values() if len(group) > 1 for n in group}

    entries = []
    for name in files:
        label = store.get(name)
        badges = label.badges if label else []
        reviewed = bool(label.reviewed) if label else False
        classified = sum(1 for b in badges if b.pct is not None)
        unknown = len(badges) - classified
        negative = reviewed and len(badges) == 0
        state = ("reviewed_negative" if negative
                 else "reviewed" if reviewed else "pending")
        prov = provenance_for(name, dataset_dir=d) or {}
        pc = Counter(b.pct for b in badges if b.pct is not None)
        entries.append(QueueEntry(
            frame=name, path=str(frames_dir / name),
            world=prov.get("alias"), timestamp=prov.get("timestamp"),
            capture_w=prov.get("capture_w"), capture_h=prov.get("capture_h"),
            detected=len(badges), classified=classified, unknown=unknown,
            reviewed=reviewed, negative=negative, review_state=state,
            duplicate=name in dup_names, session_id=prov.get("session_id"),
            source=prov.get("source", "imported"),
            per_class={str(k): pc.get(k, 0) for k in CLASSES},
        ))
    return entries


_FILTERS = {
    "unreviewed": lambda e: not e.reviewed,
    "reviewed": lambda e: e.reviewed,
    "no_badge": lambda e: e.detected == 0,
    "has_unknown": lambda e: e.unknown > 0,
    "negative": lambda e: e.negative,
}
for _c in CLASSES:
    _FILTERS[str(_c)] = (lambda c: (lambda e: e.per_class.get(str(c), 0) > 0))(_c)


def _sort_key(name: str):
    if name == "newest":
        return lambda e: (e.timestamp or "", e.frame), True
    if name == "uncertainty":       # most UNKNOWN first
        return lambda e: e.unknown, True
    if name == "most_detections":
        return lambda e: e.detected, True
    if name == "world":
        return lambda e: (e.world or "~", e.frame), False
    if name == "rarest_class":      # frames touching the scarcest classes first
        return None, False
    return lambda e: (e.timestamp or "", e.frame), True


def build_queue(dataset_dir=None, *, filters=None, world=None, resolution=None,
                today=False, session_id=None, sort="newest") -> list[QueueEntry]:
    """Filtered + sorted capture queue. ``filters`` is a list of filter names
    (see ``_FILTERS``); ``world``/``resolution``/``session_id`` narrow further;
    ``today`` keeps only frames captured today."""
    rows = frame_rows(dataset_dir)
    for f in (filters or []):
        fn = _FILTERS.get(f)
        if fn:
            rows = [e for e in rows if fn(e)]
    if world:
        rows = [e for e in rows if e.world == world]
    if resolution:
        rows = [e for e in rows if _resolution(e.capture_w, e.capture_h) == resolution]
    if session_id:
        rows = [e for e in rows if e.session_id == session_id]
    if today:
        t = date.today().isoformat()
        rows = [e for e in rows if (e.timestamp or "").startswith(t)]

    if sort == "rarest_class":
        scarcity = _class_scarcity(rows)
        rows.sort(key=lambda e: min((scarcity[int(c)] for c, n in e.per_class.items() if n),
                                    default=10 ** 9))
    else:
        key, reverse = _sort_key(sort)
        if key:
            rows.sort(key=key, reverse=reverse)
    return rows


def _class_scarcity(rows) -> dict:
    counts = Counter()
    for e in rows:
        for c in CLASSES:
            counts[c] += e.per_class.get(str(c), 0)
    return {c: counts.get(c, 0) for c in CLASSES}


# --------------------------------------------------------------------------- #
# Statistics (canonical corpus)                                               #
# --------------------------------------------------------------------------- #

def _live_or_historical(source: str) -> str:
    return "live_chrome" if source in LIVE_SOURCES else "historical"


def dataset_statistics(samples=None, *, dataset_dir=None, session_id=None) -> dict:
    """Canonical corpus statistics for the Datasets page. Uses the unified loader
    (`load_all`) by default so every reviewed frame — historical and freshly
    collected — is counted, and enriches per-World/today/session from the collected
    frames' provenance. ``samples`` may be injected (tests)."""
    if samples is None:
        from bap.forge.detection.dataset import load_all
        samples = load_all()

    total_frames = len(samples)
    reviewed_frames = total_frames   # load_all only returns reviewed frames
    total_badges = sum(len(s.badges) for s in samples)
    per_class = Counter()
    per_world = Counter()
    per_res = Counter()
    per_live = Counter()
    negatives = 0
    for s in samples:
        if len(s.badges) == 0:
            negatives += 1
        for b in s.badges:
            if b.pct is not None:
                per_class[b.pct] += 1
        per_res[_resolution(s.width, s.height)] += 1
        per_live[_live_or_historical(s.source)] += 1
        per_world[s.world or s.source] += 1

    # today / session counts from the collected frames' provenance
    entries = frame_rows(dataset_dir)
    t = date.today().isoformat()
    today_frames = sum(1 for e in entries if (e.timestamp or "").startswith(t))
    session_frames = (sum(1 for e in entries if e.session_id == session_id)
                      if session_id else 0)
    # provenance also gives per-World for collected live frames
    for e in entries:
        if e.world:
            per_world[e.world] += 0  # ensure key exists; counts come from samples

    class_counts = {str(c): per_class.get(c, 0) for c in CLASSES}
    return {
        "total_frames": total_frames,
        "reviewed_frames": reviewed_frames,
        "pending_frames": max(0, len(entries) - sum(1 for e in entries if e.reviewed)),
        "reviewed_negative_frames": negatives,
        "total_badges": total_badges,
        "per_class": class_counts,
        "per_world": dict(sorted(per_world.items(), key=lambda kv: -kv[1])),
        "per_resolution": dict(sorted(per_res.items(), key=lambda kv: -kv[1])),
        "live_vs_historical": {"live_chrome": per_live.get("live_chrome", 0),
                               "historical": per_live.get("historical", 0)},
        "today_frames": today_frames,
        "session_frames": session_frames,
        "shortages": shortage_hints(class_counts, per_live),
    }


def shortage_hints(class_counts: dict, per_live: Counter | None = None) -> dict:
    """Neutral guidance on the scarcest classes — a goal, never a promise that a
    class will appear. Lists classes with zero examples and the single most useful
    next capture."""
    zero = [c for c in CLASSES if class_counts.get(str(c), 0) == 0]
    scarce = sorted(CLASSES, key=lambda c: class_counts.get(str(c), 0))
    most_useful = scarce[0] if scarce else None
    live_scarce = bool(per_live) and per_live.get("live_chrome", 0) < 30
    return {
        "zero_example_classes": zero,
        "scarce_classes": [c for c in scarce if class_counts.get(str(c), 0) < 15],
        "most_useful_next_capture": most_useful,
        "live_chrome_scarce": live_scarce,
        "message": (f"Most useful next capture: {most_useful}%"
                    if most_useful is not None else "Balanced"),
    }


def target_progress(session, *, dataset_dir=None) -> dict:
    """Per-class + negative progress toward a session's targets, counted from the
    frames captured in that session. Never fabricates a missing class."""
    if session is None:
        return {}
    entries = [e for e in frame_rows(dataset_dir) if e.session_id == session.session_id]
    got = Counter()
    neg = 0
    for e in entries:
        if e.negative:
            neg += 1
        for c in CLASSES:
            got[c] += e.per_class.get(str(c), 0)
    out = {}
    for key, tgt in (session.targets or {}).items():
        have = neg if key == "negative" else got.get(int(key), 0) if key.isdigit() else 0
        out[key] = {"have": have, "target": tgt,
                    "remaining": max(0, tgt - have), "met": have >= tgt}
    return out


# --------------------------------------------------------------------------- #
# Active-learning priority                                                     #
# --------------------------------------------------------------------------- #

def active_learning_priority(dataset_dir=None) -> list[tuple[QueueEntry, int, list[str]]]:
    """Rank pending frames by review value using existing diagnostics only (no
    retraining, no prediction change). Returns ``(entry, score, reasons)`` sorted
    high-to-low. Higher = review sooner."""
    entries = frame_rows(dataset_dir)
    scarcity = _class_scarcity(entries)
    scored = []
    for e in entries:
        if e.reviewed:
            continue
        score, reasons = 0, []
        if e.unknown > 0:
            score += 3 * e.unknown
            reasons.append(f"{e.unknown} UNKNOWN badge(s) near the accept bar")
        rare_hits = sum(e.per_class.get(str(c), 0) for c in CLASSES
                        if scarcity.get(c, 0) <= 8)
        if rare_hits:
            score += 5 * rare_hits
            reasons.append("touches a rare class")
        res = _resolution(e.capture_w, e.capture_h)
        if res and res not in ("1920x1080",):
            score += 2
            reasons.append(f"unusual resolution {res}")
        if e.detected == 0:
            score += 1
            reasons.append("no-badge candidate (possible negative)")
        if e.source in LIVE_SOURCES:
            score += 2
            reasons.append("live Chrome frame")
        scored.append((e, score, reasons))
    scored.sort(key=lambda t: -t[1])
    return scored


__all__ = [
    "QueueEntry", "frame_rows", "build_queue", "dataset_statistics",
    "shortage_hints", "target_progress", "active_learning_priority", "CLASSES",
]
