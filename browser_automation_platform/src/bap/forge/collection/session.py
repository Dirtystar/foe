"""Named live-collection sessions that survive an app restart (Milestone 5D).

A session records *who/what/when* around a burst of live captures: an id, start
time, browser mode, the Worlds included, operator notes, the git commit the app is
running, the dataset path, and optional per-class collection targets. Sessions are
JSON files under ``dataset/collection_sessions/`` so they persist across restarts
and travel with the dataset. Nothing here captures or clicks — it is pure state.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from bap.forge.dataset_store import reviewed_dataset_dir

SESSIONS_DIRNAME = "collection_sessions"
ACTIVE_NAME = "active.txt"

# Default per-class + negative collection targets for a day of gathering. Neutral:
# a target is a goal, never a promise that a class will appear.
DEFAULT_TARGETS = {"20": 20, "40": 20, "60": 20, "80": 20, "100": 20, "negative": 20}


def sessions_dir(*, create: bool = False) -> Path:
    d = reviewed_dataset_dir(create=create) / SESSIONS_DIRNAME
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def current_git_commit() -> str | None:
    """The app's current git commit (provenance), or None outside a repo."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, cwd=str(Path(__file__).resolve().parent), timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


@dataclass
class CollectionSession:
    """One named data-collection session. Persisted as
    ``dataset/collection_sessions/<id>.json``."""
    session_id: str
    started_at: str
    browser_mode: str = "unknown"
    worlds: list[str] = field(default_factory=list)   # World aliases
    notes: str = ""
    git_commit: str | None = None
    dataset_path: str = ""
    targets: dict = field(default_factory=lambda: dict(DEFAULT_TARGETS))
    captured_frames: list[str] = field(default_factory=list)  # frame names added this session
    duplicates_skipped: int = 0
    # Crash/cancel-safe batch state for the async Capture All (Milestone 5D P0):
    # which Worlds a batch requested vs finished, so a reopened session can resume
    # only the unfinished Worlds and never re-captures completed ones.
    batch: dict = field(default_factory=lambda: {"requested": [], "done": [],
                                                 "failed": [], "cancelled": False,
                                                 "running": False})

    # ---- persistence ----
    def path(self) -> Path:
        return sessions_dir(create=True) / f"{self.session_id}.json"

    def save(self) -> "CollectionSession":
        _atomic_write(self.path(), json.dumps(asdict(self), indent=2))
        return self

    def record_capture(self, frame_name: str, *, is_new: bool) -> None:
        """Track a capture attempt. New frames join the session; a duplicate only
        bumps the skipped counter (the frame is never re-added)."""
        if is_new:
            if frame_name not in self.captured_frames:
                self.captured_frames.append(frame_name)
        else:
            self.duplicates_skipped += 1
        self.save()

    # ---- crash/cancel-safe batch tracking (async Capture All) ----
    def start_batch(self, aliases: list[str]) -> None:
        self.batch = {"requested": list(aliases), "done": [], "failed": [],
                      "cancelled": False, "running": True}
        self.save()

    def mark_batch(self, alias: str, *, ok: bool) -> None:
        key = "done" if ok else "failed"
        if alias not in self.batch.get(key, []):
            self.batch.setdefault(key, []).append(alias)
        self.save()

    def end_batch(self, *, cancelled: bool = False) -> None:
        self.batch["running"] = False
        self.batch["cancelled"] = cancelled
        self.save()

    def unfinished_worlds(self) -> list[str]:
        """Requested Worlds that neither completed nor failed — resume candidates."""
        done = set(self.batch.get("done", [])) | set(self.batch.get("failed", []))
        return [a for a in self.batch.get("requested", []) if a not in done]

    @classmethod
    def from_dict(cls, d: dict) -> "CollectionSession":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def start_session(worlds: list[str], *, browser_mode: str = "unknown",
                  notes: str = "", targets: dict | None = None,
                  session_id: str | None = None, make_active: bool = True
                  ) -> CollectionSession:
    """Create and persist a new session, and mark it active by default."""
    now = datetime.now()
    sid = session_id or now.strftime("%Y%m%d_%H%M%S")
    sess = CollectionSession(
        session_id=sid,
        started_at=now.isoformat(timespec="seconds"),
        browser_mode=browser_mode,
        worlds=list(worlds),
        notes=notes,
        git_commit=current_git_commit(),
        dataset_path=str(reviewed_dataset_dir()),
        targets=dict(targets) if targets else dict(DEFAULT_TARGETS),
    )
    sess.save()
    if make_active:
        set_active(sid)
    return sess


def load_session(session_id: str) -> CollectionSession | None:
    p = sessions_dir() / f"{session_id}.json"
    if not p.exists():
        return None
    return CollectionSession.from_dict(json.loads(p.read_text()))


def list_sessions() -> list[CollectionSession]:
    d = sessions_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(CollectionSession.from_dict(json.loads(p.read_text())))
        except Exception:
            continue
    return sorted(out, key=lambda s: s.started_at, reverse=True)


def set_active(session_id: str) -> None:
    _atomic_write(sessions_dir(create=True) / ACTIVE_NAME, session_id)


def active_session() -> CollectionSession | None:
    """The session marked active (survives restart), or None."""
    marker = sessions_dir() / ACTIVE_NAME
    if not marker.exists():
        return None
    return load_session(marker.read_text().strip())


__all__ = [
    "CollectionSession", "start_session", "load_session", "list_sessions",
    "active_session", "set_active", "sessions_dir", "current_git_commit",
    "DEFAULT_TARGETS",
]
