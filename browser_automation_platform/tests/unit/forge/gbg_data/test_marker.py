"""Parsing a province's screen point out of FoE Helper's marker-arrow transform."""

from __future__ import annotations

from bap.forge.gbg_data.marker import parse_marker_xy


def test_parses_translate_with_scale():
    # exactly the shape observed live: translate(Xpx, Ypx) scale(1)
    assert parse_marker_xy("translate(1332px, 663px) scale(1);") == (1332.0, 663.0)


def test_parses_bare_translate():
    assert parse_marker_xy("transform: translate(10px, 20px);") == (10.0, 20.0)


def test_handles_negative_offscreen_coords():
    # an off-screen sector: the anchor can be negative or beyond the viewport
    assert parse_marker_xy("translate(-140px, 512px) scale(1)") == (-140.0, 512.0)


def test_tolerates_extra_whitespace_and_floats():
    assert parse_marker_xy("translate(  1200.5px ,  48.25px ) scale(1)") == (1200.5, 48.25)


def test_blank_or_missing_is_none():
    assert parse_marker_xy("") is None
    assert parse_marker_xy(None) is None
    assert parse_marker_xy("rotate(45deg)") is None
