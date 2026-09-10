"""Province naming: the guild's file wins, the generated grid fills in, ids never collide."""

from __future__ import annotations

import json
from pathlib import Path

from bap.alerting.labels import LabelBook, auto_labels, load_label_file
from bap.forge.gbg_data.map_layout import MapLayout


def _layout(flags):
    return MapLayout(map_id="m", width=2500, height=1960, flags=flags)


def test_load_plain_and_wrapped_forms(tmp_path):
    plain = tmp_path / "a.json"
    plain.write_text(json.dumps({"14": "A1X", "7": " B2 "}), encoding="utf-8")
    assert load_label_file(plain) == {14: "A1X", 7: "B2"}

    wrapped = tmp_path / "b.json"
    wrapped.write_text(json.dumps({"map_id": "m", "labels": {"3": "C9"}}), encoding="utf-8")
    assert load_label_file(wrapped) == {3: "C9"}


def test_load_tolerates_junk(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_label_file(bad) == {}
    assert load_label_file(tmp_path / "missing.json") == {}
    mixed = tmp_path / "m.json"
    mixed.write_text(json.dumps({"x": "A1", "2": "", "3": "OK"}), encoding="utf-8")
    assert load_label_file(mixed) == {3: "OK"}


def test_auto_labels_are_positional():
    """A 4x4 grid, matching the sector shape the guild says out loud (A1 … D4)."""
    labels = auto_labels(_layout({1: (0, 0), 2: (2500, 0), 3: (0, 1960)}))
    assert labels[1] == "A1"                                          # top-left
    assert labels[2].startswith("D")                                  # far right column
    assert labels[3] == "A4"                                          # bottom-left


def test_auto_labels_never_collide():
    flags = {i: (1000 + i, 1000 + i) for i in range(6)}   # all inside one cell
    labels = auto_labels(_layout(flags))
    assert len(set(labels.values())) == len(flags)


def test_colliding_labels_take_the_guilds_letter_suffix_shape():
    """Provinces sharing a cell read like the guild's own names (C3, C3B, C3C), not F7b."""
    # two far corners set the bounding box; 1/2/3 are clustered inside one cell of it
    flags = {8: (0, 0), 9: (3000, 2000), 1: (100, 100), 2: (110, 110), 3: (120, 120)}
    labels = auto_labels(_layout(flags))
    assert [labels[1], labels[2], labels[3]] == ["A1", "A1B", "A1C"]


def test_auto_labels_handle_a_single_province():
    assert auto_labels(_layout({4: (10, 10)})) == {4: "A1"}


def test_no_layout_no_auto_labels():
    assert auto_labels(None) == {}
    assert auto_labels(_layout({})) == {}


def test_book_precedence(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"1": "A1X"}), encoding="utf-8")
    book = LabelBook.build(path=path, layout=_layout({1: (0, 0), 2: (2500, 1960)}))
    assert book.label(1) == "A1X"            # guild name wins over the grid
    assert book.label(2) == "D4"             # grid fills in
    assert book.label(99) == "#99"           # unknown province stays identifiable
    assert book.named_ids() == {1}


def test_with_layout_keeps_overrides(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"1": "A1X"}), encoding="utf-8")
    book = LabelBook.build(path=path).with_layout(_layout({1: (0, 0), 2: (100, 100)}))
    assert book.label(1) == "A1X" and book.label(2) != "#2"


# ----------------------------------------------------------------- hex rings

def _waterfall():
    """The live 61-province map: a centred hexagon, 1+6+12+18+24."""
    from bap.forge.gbg_data.map_layout import parse_map_data

    path = Path("dataset/api_samples/map_data.waterfall_archipelago.sample.json")
    return parse_map_data(json.loads(path.read_text(encoding="utf-8")))


def test_a_real_map_decomposes_into_exact_hex_rings():
    """The naming scheme is positional — number = ring, letter = sector — and that only works
    if the map really is a centred hexagon. On the live map every one of the 24 (ring, sector)
    cells holds exactly as many provinces as the ring index says it should."""
    from collections import Counter

    from bap.alerting.labels import hex_cells

    cells = hex_cells(_waterfall())
    assert Counter(r for r, _, _ in cells.values()) == {0: 1, 1: 6, 2: 12, 3: 18, 4: 24}
    per_cell = Counter((r, s) for r, s, _ in cells.values() if r)
    assert all(per_cell[(r, s)] == r for r in range(1, 5) for s in range(6))


def test_a_map_that_is_not_a_hexagon_is_left_alone():
    from bap.alerting.labels import hex_cells

    assert hex_cells(_layout({i: (i * 10, i * 7) for i in range(5)})) == {}
    assert hex_cells(None) == {}


def test_ring_labels_are_unique_and_shaped_like_the_game_says_them():
    import re

    from bap.alerting.labels import ring_labels

    labels = ring_labels(_waterfall())
    assert len(labels) == 60                      # every province but the centre
    assert len(set(labels.values())) == 60
    assert all(re.fullmatch(r"[A-F][2-5][A-D]", v) for v in labels.values())


def test_fitting_recovers_the_settings_from_a_handful_of_known_labels():
    """A dozen labels read off the map pin the scheme down — which is the difference between
    typing sixty names and typing none."""
    from bap.alerting.labels import fit_ring_labels, ring_labels

    layout = _waterfall()
    truth = ring_labels(layout, ring_base=0, sector_origin=3, clockwise=True)
    known = {pid: truth[pid] for pid in sorted(truth)[:12]}
    labels, settings, hits, total = fit_ring_labels(layout, known)
    assert (hits, total) == (12, 12)
    assert settings == {"ring_base": 0, "sector_origin": 3, "clockwise": True}
    assert labels == truth
