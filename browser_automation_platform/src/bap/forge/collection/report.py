"""Exportable per-session collection report (Milestone 5D).

Writes ``LIVE_COLLECTION_SESSION_<id>.md`` summarising a collection session: the
Worlds, captures, duplicates skipped, review state, negatives, per-class counts,
resolution/source distribution, dataset validation, and the recommended next data
gaps. Read-only over the dataset.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from bap.forge.collection.dataset_view import (
    CLASSES,
    dataset_statistics,
    frame_rows,
    target_progress,
)
from bap.forge.collection.validate import validate_dataset


def session_report(session, *, dataset_dir=None) -> str:
    """Build the markdown report for ``session`` (does not write it)."""
    entries = [e for e in frame_rows(dataset_dir) if e.session_id == session.session_id]
    reviewed = [e for e in entries if e.reviewed]
    pending = [e for e in entries if not e.reviewed]
    negatives = [e for e in entries if e.negative]
    per_class = Counter()
    res_dist = Counter()
    world_dist = Counter()
    for e in entries:
        for c in CLASSES:
            per_class[c] += e.per_class.get(str(c), 0)
        if e.capture_w and e.capture_h:
            res_dist[f"{e.capture_w}x{e.capture_h}"] += 1
        if e.world:
            world_dist[e.world] += 1

    val = validate_dataset(dataset_dir=dataset_dir)
    stats = dataset_statistics(dataset_dir=dataset_dir, session_id=session.session_id)
    prog = target_progress(session, dataset_dir=dataset_dir)

    L = []
    L.append(f"# Live Collection Session {session.session_id}")
    L.append("")
    L.append(f"- Started: {session.started_at}")
    L.append(f"- Browser mode: {session.browser_mode}")
    L.append(f"- Worlds: {', '.join(session.worlds) or '(none recorded)'}")
    L.append(f"- Git commit: {session.git_commit or '(unknown)'}")
    L.append(f"- Dataset: {session.dataset_path}")
    if session.notes:
        L.append(f"- Notes: {session.notes}")
    L.append("")
    L.append("## Captures")
    L.append(f"- Frames captured this session: **{len(entries)}**")
    L.append(f"- Duplicates skipped: **{session.duplicates_skipped}**")
    L.append(f"- Reviewed: **{len(reviewed)}**   ·   Pending: **{len(pending)}**   "
             f"·   Reviewed negatives: **{len(negatives)}**")
    L.append("")
    L.append("## Badges by class (this session)")
    L.append("| class | count |")
    L.append("|---|---|")
    for c in CLASSES:
        L.append(f"| {c}% | {per_class.get(c, 0)} |")
    L.append("")
    if prog:
        L.append("## Target progress")
        L.append("| target | have | goal | met |")
        L.append("|---|---|---|---|")
        for k, v in prog.items():
            L.append(f"| {k} | {v['have']} | {v['target']} | {'✅' if v['met'] else '—'} |")
        L.append("")
    L.append("## Distribution")
    L.append(f"- Resolutions: {dict(res_dist) or '(none)'}")
    L.append(f"- Worlds: {dict(world_dist) or '(none)'}")
    L.append("")
    L.append("## Dataset validation")
    L.append(f"- {'✅ OK' if val['ok'] else '❌ errors present'} — "
             f"{val['counts']['errors']} error(s), {val['counts']['warnings']} warning(s)")
    L.append("")
    L.append("## Canonical corpus after this session")
    L.append(f"- Per class: {stats['per_class']}")
    L.append(f"- Live Chrome vs historical: {stats['live_vs_historical']}")
    L.append("")
    L.append("## Recommended next data gaps")
    sh = stats["shortages"]
    if sh["zero_example_classes"]:
        L.append(f"- Zero examples: {', '.join(f'{c}%' for c in sh['zero_example_classes'])}")
    if sh["scarce_classes"]:
        L.append(f"- Scarce (<15): {', '.join(f'{c}%' for c in sh['scarce_classes'])}")
    L.append(f"- {sh['message']} (a goal, not a guarantee the class will appear)")
    if sh["live_chrome_scarce"]:
        L.append("- Live-Chrome examples remain scarce — prefer live captures.")
    L.append("")
    return "\n".join(L)


def write_session_report(session, *, dataset_dir=None, out_dir=None) -> str:
    """Write the report to ``LIVE_COLLECTION_SESSION_<id>.md`` and return the path."""
    text = session_report(session, dataset_dir=dataset_dir)
    out = Path(out_dir) if out_dir is not None else Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"LIVE_COLLECTION_SESSION_{session.session_id}.md"
    path.write_text(text)
    return str(path)


__all__ = ["session_report", "write_session_report"]
