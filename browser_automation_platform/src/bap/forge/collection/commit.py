"""Prepare a dataset commit (Milestone 5D) — **never runs git**.

Shows the operator what changed and the exact Git Bash commands to run themselves.
Reads git state read-only (status + the committed labels.json) to compute file and
class-count deltas. If unreviewed frames are included it warns, but still allows them
to remain as pending data.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

from bap.forge.collection.dataset_view import CLASSES
from bap.forge.collection.validate import validate_dataset
from bap.forge.dataset_store import FRAMES_DIRNAME, LABELS_NAME, reviewed_dataset_dir


def _git(args, cwd) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True,
                           cwd=str(cwd), timeout=15)
        return p.returncode, (p.stdout if p.returncode == 0 else p.stderr)
    except Exception as e:  # pragma: no cover - git absent
        return 1, str(e)


def _repo_root(start: Path) -> Path | None:
    rc, out = _git(["rev-parse", "--show-toplevel"], start)
    return Path(out.strip()) if rc == 0 and out.strip() else None


def _iter_frames(text_or_data):
    """Yield frame records from labels.json, tolerating the list or dict shape."""
    data = text_or_data if isinstance(text_or_data, dict) else json.loads(text_or_data)
    frames = data.get("frames", [])
    records = frames.values() if isinstance(frames, dict) else frames
    for fl in records:
        if isinstance(fl, dict):
            yield fl


def _class_counts_from_labels(text: str) -> Counter:
    counts = Counter()
    try:
        for fl in _iter_frames(text):
            for b in fl.get("badges", []):
                if b.get("pct") in CLASSES:
                    counts[b["pct"]] += 1
    except Exception:
        pass
    return counts


def prepare_commit(session=None, dataset_dir=None) -> dict:
    """Return a plan the operator executes manually: changed files, reviewed count,
    per-class delta vs HEAD, validation status, warnings, and suggested commands."""
    d = Path(dataset_dir) if dataset_dir is not None else reviewed_dataset_dir()
    root = _repo_root(d)
    rel = None
    if root is not None:
        try:
            rel = d.relative_to(root).as_posix()
        except ValueError:
            rel = None

    changed = {"added": [], "modified": [], "deleted": []}
    if root is not None and rel is not None:
        rc, out = _git(["status", "--porcelain", "--", rel], root)
        if rc == 0:
            for line in out.splitlines():
                code, _, path = line.partition(" ")[0], None, line[3:]
                if line[:2].strip() in ("A", "??"):
                    changed["added"].append(path)
                elif "M" in line[:2]:
                    changed["modified"].append(path)
                elif "D" in line[:2]:
                    changed["deleted"].append(path)

    # per-class delta vs the committed labels.json
    labels_rel = f"{rel}/{LABELS_NAME}" if rel else None
    head_counts = Counter()
    if root is not None and labels_rel is not None:
        rc, out = _git(["show", f"HEAD:{labels_rel}"], root)
        if rc == 0:
            head_counts = _class_counts_from_labels(out)
    cur_counts = Counter()
    cur_labels = d / LABELS_NAME
    if cur_labels.exists():
        cur_counts = _class_counts_from_labels(cur_labels.read_text())
    class_delta = {str(c): cur_counts.get(c, 0) - head_counts.get(c, 0) for c in CLASSES}

    # reviewed / pending counts
    reviewed = pending = 0
    if cur_labels.exists():
        try:
            for fl in _iter_frames(cur_labels.read_text()):
                if fl.get("reviewed"):
                    reviewed += 1
                else:
                    pending += 1
        except Exception:
            pass

    validation = validate_dataset(dataset_dir=d)
    warnings = []
    if pending:
        warnings.append(f"{pending} unreviewed (pending) frame(s) are included — "
                        "they will be committed as pending data, not ground truth.")
    if not validation["ok"]:
        warnings.append(f"{validation['counts']['errors']} integrity error(s) — "
                        "run Validate Dataset and fix before committing.")

    sid = getattr(session, "session_id", None) if session else None
    add_target = rel or "dataset/"
    commands = [
        f"git add {add_target}",
        f'git commit -m "Add live collection {sid or Path(add_target).name}"',
        "git pull --rebase origin <branch>",
        "git push origin <branch>",
    ]
    return {
        "dataset_dir": str(d),
        "git_repo": str(root) if root else None,
        "files": changed,
        "files_added": len(changed["added"]),
        "files_modified": len(changed["modified"]),
        "frames_reviewed": reviewed,
        "frames_pending": pending,
        "class_count_delta": class_delta,
        "validation_ok": validation["ok"],
        "validation_counts": validation["counts"],
        "warnings": warnings,
        "suggested_commands": commands,
    }


__all__ = ["prepare_commit"]
