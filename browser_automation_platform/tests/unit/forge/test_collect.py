"""Tooling — `bap.forge.collect`: summarise and export the frames the app saved
while playing, ready to commit. Read-only over the game; idempotent export."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from bap.forge import collect


def _bundle(captures_dir, name, *, world="H", state="PROVINCE_PANEL", image=True):
    d = captures_dir / name
    d.mkdir(parents=True)
    if image:
        cv2.imwrite(str(d / "screen.png"), np.zeros((10, 12, 3), np.uint8))
    (d / "classification.json").write_text(json.dumps({"state": state}))
    (d / "context.json").write_text(json.dumps(
        {"observed_state": state, "world": world}))
    return d


def test_scan_classifies_panel_and_unknown(tmp_path):
    cap = tmp_path / "captures"
    _bundle(cap, "panel_20260830_1", state="PROVINCE_PANEL")
    _bundle(cap, "unknown_20260830_2", state="GBG_MAP")
    bundles = collect.scan(cap)
    kinds = sorted(b.kind for b in bundles)
    assert kinds == ["panel", "unknown"]
    assert all(b.has_image for b in bundles)


def test_scan_empty_dir_is_no_crash(tmp_path):
    assert collect.scan(tmp_path / "nope") == []


def test_bundle_missing_image_is_flagged(tmp_path):
    cap = tmp_path / "captures"
    _bundle(cap, "unknown_1", image=False)
    (b,) = collect.scan(cap)
    assert b.has_image is False
    assert "no screen.png" in collect.summarise([b])


def test_export_copies_named_frames_and_manifest(tmp_path):
    cap = tmp_path / "captures"
    _bundle(cap, "panel_ts1", world="H", state="PROVINCE_PANEL")
    _bundle(cap, "unknown_ts2", world="F", state="GBG_MAP")
    out = tmp_path / "panels"
    exported, skipped = collect.export(collect.scan(cap), out)
    assert exported == 2 and skipped == 0
    names = sorted(p.name for p in out.glob("*.png"))
    assert names == ["gbg_map_F_ts2.png", "province_panel_H_ts1.png"]
    rows = list(csv.DictReader((out / "manifest.csv").open()))
    assert {r["world"] for r in rows} == {"H", "F"}
    assert rows[0]["filename"].endswith(".png")


def test_export_is_idempotent(tmp_path):
    cap = tmp_path / "captures"
    _bundle(cap, "panel_ts1")
    out = tmp_path / "panels"
    assert collect.export(collect.scan(cap), out) == (1, 0)
    # second run: nothing new, the existing frame is skipped (not duplicated)
    assert collect.export(collect.scan(cap), out) == (0, 1)
    assert len(list(out.glob("*.png"))) == 1
    # manifest has exactly one data row (header written once)
    assert len(list(csv.DictReader((out / "manifest.csv").open()))) == 1


def test_export_skips_bundle_without_image(tmp_path):
    cap = tmp_path / "captures"
    _bundle(cap, "unknown_noimg", image=False)
    out = tmp_path / "panels"
    assert collect.export(collect.scan(cap), out) == (0, 0)


def test_main_summary_no_captures(tmp_path, capsys):
    rc = collect.main(["--captures-dir", str(tmp_path / "captures")])
    assert rc == 0
    assert "Nothing collected yet" in capsys.readouterr().out


def test_main_export_reports_count(tmp_path, capsys):
    cap = tmp_path / "captures"
    _bundle(cap, "panel_ts1")
    rc = collect.main(["--captures-dir", str(cap), "--export",
                       "--out", str(tmp_path / "panels")])
    assert rc == 0
    assert "Exported 1 new frame" in capsys.readouterr().out
