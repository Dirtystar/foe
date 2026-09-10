"""Milestone 4.5 — Test-Scan World routing, stale-callback prevention, and
multi-World independence (observe-only, no Qt).

Proves the Windows-review acceptance criteria at the logic layer: the scan runs
against the explicitly selected World, resolves that World's tab fresh at scan
time, never falls back to another World or an offline image, and scales to
independent 4/8-World collections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.app.attended import TabAssignment
from bap.core.domain.models import BrowserTab
from bap.forge.detection.testscan import (
    attached_aliases,
    capture_world_image,
    resolve_target,
    scan_all_attached,
    scan_world,
)
from bap.forge.worlds import World, WorldStore


def _store(*aliases_hosts):
    store = WorldStore()
    for alias, host in aliases_hosts:
        store.add(World(alias=alias, hostname=host))
    return store


def _tab(tab_id, host):
    return BrowserTab(tab_id, f"{host} title", f"https://{host}/game/index")


class FakeCapture:
    """Encodes a distinct 1-px-colored PNG per tab id and records every tab id it
    was asked to capture, so tests can prove which tab each scan used."""

    def __init__(self, sizes=None):
        self.calls: list[str] = []
        self._sizes = sizes or {}

    def __call__(self, tab_id: str) -> bytes:
        self.calls.append(tab_id)
        w, h = self._sizes.get(tab_id, (64, 48))
        img = np.zeros((h, w, 3), np.uint8)
        ok, buf = cv2.imencode(".png", img)
        return buf.tobytes() if ok else b""


def _hf():
    store = _store(("H", "cz8.forgeofempires.com"), ("F", "cz6.forgeofempires.com"))
    asn = TabAssignment()
    asn.assign("H", _tab("tab-H", "cz8.forgeofempires.com"))
    asn.assign("F", _tab("tab-F", "cz6.forgeofempires.com"))
    return store, asn


# --- target resolution --------------------------------------------------------


def test_resolve_target_uses_selected_world_not_first():
    store, asn = _hf()
    t = resolve_target("F", world_store=store, assignment=asn, browser_open=True)
    assert t.alias == "F" and t.attached and t.tab_id == "tab-F"
    assert t.hostname == "cz6.forgeofempires.com"


def test_resolve_target_unattached_reports_error_no_fallback():
    store, asn = _hf()
    asn.clear("F")
    t = resolve_target("F", world_store=store, assignment=asn, browser_open=True)
    assert not t.attached and "not attached" in t.error
    assert t.tab_id is None


def test_resolve_target_browser_closed():
    store, asn = _hf()
    t = resolve_target("H", world_store=store, assignment=asn, browser_open=False)
    assert not t.attached and "not open" in t.error


# --- capture routing (H scans H, F scans F) -----------------------------------


def test_capture_uses_the_selected_worlds_tab():
    store, asn = _hf()
    cap = FakeCapture()
    img_h, err_h = capture_world_image("H", world_store=store, assignment=asn,
                                       browser_open=True, capture_callback=cap)
    img_f, err_f = capture_world_image("F", world_store=store, assignment=asn,
                                       browser_open=True, capture_callback=cap)
    assert err_h is None and err_f is None
    assert cap.calls == ["tab-H", "tab-F"]        # each used its own tab handle


def test_no_offline_or_cross_world_fallback_when_unattached():
    store, asn = _hf()
    asn.clear("F")
    cap = FakeCapture()
    img, err = capture_world_image("F", world_store=store, assignment=asn,
                                   browser_open=True, capture_callback=cap)
    assert img is None and "not attached" in err
    assert cap.calls == []                         # never captured another World


def test_capture_failure_is_reported_not_swallowed():
    store, asn = _hf()

    def boom(_tab_id):
        raise RuntimeError("tab closed")

    img, err = capture_world_image("H", world_store=store, assignment=asn,
                                   browser_open=True, capture_callback=boom)
    assert img is None and "live capture failed" in err


# --- stale-callback / reorder / delete safety ---------------------------------


def test_tab_resolved_fresh_after_reassignment():
    store, asn = _hf()
    cap = FakeCapture()
    capture_world_image("H", world_store=store, assignment=asn, browser_open=True,
                        capture_callback=cap)
    # The user re-scans and H reattaches to a different tab id.
    asn.assign("H", _tab("tab-H2", "cz8.forgeofempires.com"))
    capture_world_image("H", world_store=store, assignment=asn, browser_open=True,
                        capture_callback=cap)
    assert cap.calls == ["tab-H", "tab-H2"]        # no stale first handle retained


def test_removing_h_does_not_break_f():
    store, asn = _hf()
    store.remove("H")
    asn.clear("H")
    cap = FakeCapture()
    img, err = capture_world_image("F", world_store=store, assignment=asn,
                                   browser_open=True, capture_callback=cap)
    assert err is None and cap.calls == ["tab-F"]
    # H is gone; asking for it errors cleanly, never redirects to F.
    _img, err_h = capture_world_image("H", world_store=store, assignment=asn,
                                      browser_open=True, capture_callback=cap)
    assert err_h == "World not found" and cap.calls == ["tab-F"]


# --- scan_all independence ----------------------------------------------------


def test_scan_all_scans_each_world_with_its_own_tab():
    store, asn = _hf()
    cap = FakeCapture()
    results = scan_all_attached(world_store=store, assignment=asn, browser_open=True,
                                capture_callback=cap)
    by_alias = {r.alias: r for r in results}
    assert set(by_alias) == {"H", "F"}
    assert by_alias["H"].tab_id == "tab-H" and by_alias["H"].hostname == "cz8.forgeofempires.com"
    assert by_alias["F"].tab_id == "tab-F" and by_alias["F"].hostname == "cz6.forgeofempires.com"
    assert all(r.capture_ok for r in results)
    assert sorted(cap.calls) == ["tab-F", "tab-H"]


def test_scan_all_only_attached_worlds():
    store, asn = _hf()
    asn.clear("F")                                  # F attached no more
    cap = FakeCapture()
    results = scan_all_attached(world_store=store, assignment=asn, browser_open=True,
                                capture_callback=cap)
    assert [r.alias for r in results] == ["H"]
    assert cap.calls == ["tab-H"]


def test_eight_worlds_remain_independent():
    hosts = [(chr(ord("A") + i), f"cz{i}.forgeofempires.com") for i in range(8)]
    store = _store(*hosts)
    asn = TabAssignment()
    for alias, host in hosts:
        asn.assign(alias, _tab(f"tab-{alias}", host))
    cap = FakeCapture()
    results = scan_all_attached(world_store=store, assignment=asn, browser_open=True,
                                capture_callback=cap)
    assert len(results) == 8
    # Every World scanned exactly its own tab, once, in order.
    assert cap.calls == [f"tab-{a}" for a, _ in hosts]
    for (alias, host), r in zip(hosts, results):
        assert r.alias == alias and r.tab_id == f"tab-{alias}" and r.hostname == host


def test_attached_aliases_requires_browser_and_tab():
    store, asn = _hf()
    assert attached_aliases(world_store=store, assignment=asn, browser_open=True) == ["H", "F"]
    assert attached_aliases(world_store=store, assignment=asn, browser_open=False) == []
    asn.clear("H")
    assert attached_aliases(world_store=store, assignment=asn, browser_open=True) == ["F"]


def test_scan_all_saves_per_world_artifacts(tmp_path):
    store, asn = _hf()
    cap = FakeCapture(sizes={"tab-H": (1920, 1080), "tab-F": (1920, 1080)})
    results = scan_all_attached(world_store=store, assignment=asn, browser_open=True,
                                capture_callback=cap, artifacts_root=tmp_path)
    # Each World's artifacts land in its OWN alias directory — provably per-World.
    for r in results:
        assert r.artifacts_dir is not None
        d = Path(r.artifacts_dir)
        assert d.name == r.alias                       # scan_all/<ts>/<alias>/
        assert (d / "scan.json").exists()
        assert (d / "01_full_raw_capture.png").exists()
    # The H and F runs are in the same timestamped run but distinct alias dirs.
    parents = {Path(r.artifacts_dir).parent for r in results}
    assert len(parents) == 1
    assert {Path(r.artifacts_dir).name for r in results} == {"H", "F"}


def test_scan_all_result_carries_its_own_image():
    store, asn = _hf()
    cap = FakeCapture()
    results = scan_all_attached(world_store=store, assignment=asn, browser_open=True,
                                capture_callback=cap)
    assert all(r.image is not None for r in results)   # for the Open-result button


def test_scan_world_row_is_tagged_to_its_world():
    store, asn = _hf()
    cap = FakeCapture()
    r = scan_world("F", world_store=store, assignment=asn, browser_open=True,
                   capture_callback=cap)
    row = r.row()
    assert row["alias"] == "F" and row["hostname"] == "cz6.forgeofempires.com"
    assert row["tab_id"] == "tab-F" and row["capture"] == "ok"
    assert "stage1_candidates" in row and "accepted_detections" in row
