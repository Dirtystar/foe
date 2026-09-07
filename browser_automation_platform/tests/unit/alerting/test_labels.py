"""Province naming: the guild's file wins, the generated grid fills in, ids never collide."""

from __future__ import annotations

import json

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
