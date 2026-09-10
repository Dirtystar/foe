"""CLI surface for the Performance Observatory (Milestone 4.9).

Only the fast, browser-free paths are exercised end-to-end (argument parsing and
the `compare` subcommand). The `synthetic`/`stress` subcommands run the real
pipeline and are covered structurally by the benchmark tests, so here we only
assert their parser wiring — never invoke a heavy run in the suite.
"""

from __future__ import annotations

import json

from bap.perf.__main__ import _int_list, build_parser, main


def test_int_list_parsing():
    assert _int_list("1,2,4,8") == [1, 2, 4, 8]
    assert _int_list(" 100, 1000 ") == [100, 1000]
    assert _int_list("") == []


def test_parser_accepts_subcommands():
    p = build_parser()
    assert p.parse_args(["synthetic", "--worlds", "1,2", "--ticks", "5"]).command == "synthetic"
    assert p.parse_args(["stress", "--ticks", "100,1000"]).command == "stress"
    assert p.parse_args(["compare", "a.json", "b.json"]).command == "compare"


def _write(path, mean, p95, fps):
    path.write_text(json.dumps({
        "label": path.stem, "kind": "stress",
        "global": {"unit": "ms", "mean": mean, "median": mean, "p95": p95, "p99": p95 + 1,
                   "worst": p95 + 2, "fps": fps, "count": 10},
        "stage_breakdown": {}, "worlds": {}, "system": {}, "machine": {}, "config": {}, "extra": {},
    }), encoding="utf-8")


def test_compare_command_exit_codes(tmp_path, capsys):
    base = tmp_path / "baseline.json"
    slow = tmp_path / "current.json"
    _write(base, 10.0, 15.0, 100.0)
    _write(slow, 13.0, 20.0, 70.0)
    # A regression -> non-zero exit so CI can gate on it.
    rc = main(["compare", str(base), str(slow), "--out", str(tmp_path / "cmp.md")])
    assert rc == 1
    assert "Regression comparison" in capsys.readouterr().out
    assert (tmp_path / "cmp.md").exists()

    # No meaningful change -> exit 0.
    same = tmp_path / "same.json"
    _write(same, 10.1, 15.1, 99.0)
    assert main(["compare", str(base), str(same)]) == 0
