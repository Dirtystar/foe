"""The repo-root ``dataset/`` (imported snapshots) is a first-class reviewed
source (Milestone 4.13b).

Pins the wiring so that snapshots imported via "Import Snapshot into Dataset" are
discovered automatically by both the classifier (`default_label_sources`) and the
evaluation loader (`load_all` / `load_snapshot_dataset`) — *once reviewed*. An
imported-but-unreviewed frame must be skipped (the standing ground-truth gate),
exactly like the committed 2026-08-04 H snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from bap.forge.detection.classify import (
    default_assets_root,
    default_label_sources,
    default_snapshot_dataset_dir,
)
from bap.forge.detection.dataset import load_all, load_snapshot_dataset


def _make_dataset(base: Path, *, reviewed: bool, pct=20, badges=1) -> Path:
    """Create a minimal snapshot-style dataset: frames/<one>.png + labels.json."""
    frames = base / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    img = np.full((120, 160, 3), 40, dtype=np.uint8)
    name = "2099-01-01_00-00-00_T.png"
    cv2.imwrite(str(frames / name), img)
    label = {
        "version": 1,
        "frames": [{
            "file": name,
            "badges": [{"cx": 40 + 10 * i, "cy": 60, "pct": pct} for i in range(badges)],
            "reviewed": reviewed,
            "weakening": None,
        }],
    }
    (base / "labels.json").write_text(json.dumps(label), encoding="utf-8")
    return base


# --- discovery of the real repo dataset/ -----------------------------------


def test_repo_dataset_dir_is_discovered():
    d = default_snapshot_dataset_dir()
    assert d is not None, "repo-root dataset/ must be discovered by walk-up"
    assert (d / "labels.json").exists() and (d / "frames").is_dir()


def test_dataset_is_a_classifier_source():
    sources = default_label_sources(default_assets_root())
    names = [Path(f).parent.name for f, _ in sources]
    assert "dataset" in names, "dataset/ must be a first-class classifier source"
    # Existing sources are preserved.
    for existing in ("grading", "live_review", "review_batch_002"):
        assert existing in names


# --- reviewed vs unreviewed gate -------------------------------------------


def test_reviewed_snapshot_is_loaded(tmp_path):
    base = _make_dataset(tmp_path / "dataset", reviewed=True, pct=20, badges=2)
    samples = load_snapshot_dataset(base)
    assert len(samples) == 1, "a reviewed imported snapshot must load"
    s = samples[0]
    assert s.source == "snapshot"
    assert len(s.badges) == 2 and all(b.pct == 20 for b in s.badges)


def test_unreviewed_snapshot_is_skipped(tmp_path):
    # Mirrors the committed 2026-08-04 H frame: imported but reviewed=false.
    base = _make_dataset(tmp_path / "dataset", reviewed=False)
    assert load_snapshot_dataset(base) == [], "an unreviewed snapshot must not load"


def test_absent_dataset_is_a_noop(tmp_path):
    assert load_snapshot_dataset(tmp_path / "does-not-exist") == []


def test_load_all_includes_reviewed_snapshots_and_dedups(tmp_path):
    base = _make_dataset(tmp_path / "dataset", reviewed=True, pct=60, badges=1)
    combined = load_all(snapshots=base)
    snaps = [s for s in combined if s.source == "snapshot"]
    assert len(snaps) == 1, "load_all must include a reviewed imported snapshot"
    # De-dup by content: importing the identical image again keeps it counted once.
    combined2 = load_all(snapshots=base)
    assert sum(1 for s in combined2 if s.source == "snapshot") == 1
