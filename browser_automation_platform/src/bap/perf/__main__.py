"""Command-line entry point for the Performance Observatory (Milestone 4.9).

Examples:
    python -m bap.perf synthetic --worlds 1,2,4,8 --ticks 100 --out perf_out
    python -m bap.perf stress --ticks 100,1000,10000 --out perf_out
    python -m bap.perf compare baseline.json current.json --out cmp.md

All benchmarks are offline (no browser) and deterministic. Nothing here changes
pipeline behaviour — it only measures and reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _int_list(text: str) -> list[int]:
    return [int(x) for x in text.replace(" ", "").split(",") if x]


def _cmd_synthetic(args) -> int:
    from bap.perf import export
    from bap.perf.benchmark import run_synthetic_suite

    results = run_synthetic_suite(tuple(_int_list(args.worlds)), ticks_per_world=args.ticks)
    for r in results:
        print(f"[{r.label}] mean={r.global_summary['mean']}{r.global_summary['unit']} "
              f"p95={r.global_summary['p95']} fps/world={r.global_summary['fps']} "
              f"throughput={r.extra.get('throughput_fps')} fps  "
              f"peakRAM={r.system.get('peak_ram_mb')}MB avgCPU={r.system.get('avg_cpu_percent')}%")
    if args.out:
        written = export.write_suite(results, args.out, stem="synthetic", formats=args.formats)
        print("wrote:", written)
    return 0


def _cmd_stress(args) -> int:
    from bap.perf import export
    from bap.perf.benchmark import run_stress_suite

    results = run_stress_suite(tuple(_int_list(args.ticks)))
    for r in results:
        g = r.global_summary
        print(f"[{r.label}] avg={g['mean']}{g['unit']} median={g['median']} "
              f"p95={g['p95']} p99={g['p99']} max={g['worst']}  "
              f"throughput={r.extra.get('throughput_fps')} fps")
    if args.out:
        written = export.write_suite(results, args.out, stem="stress", formats=args.formats)
        print("wrote:", written)
    return 0


def _load(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # Accept a single result or a suite list (compare the first entry of each).
    return data[0] if isinstance(data, list) else data


def _cmd_compare(args) -> int:
    from bap.perf import compare as cmp_mod

    cmp = cmp_mod.compare(_load(args.baseline), _load(args.current), tolerance=args.tolerance)
    md = cmp_mod.to_markdown(cmp)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"\nwrote: {args.out}")
    # Non-zero exit if any regression, so CI can gate on it.
    return 1 if cmp.regressions else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m bap.perf",
                                description="Forge Performance Observatory (measurement only).")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("synthetic", help="1/2/4/8-World offline replay")
    s.add_argument("--worlds", default="1,2,4,8")
    s.add_argument("--ticks", type=int, default=100, help="ticks per World")
    s.add_argument("--out", default=None, help="output directory")
    s.add_argument("--formats", default="json,csv,md", type=lambda t: tuple(t.split(",")))
    s.set_defaults(func=_cmd_synthetic)

    st = sub.add_parser("stress", help="100/1k/10k/100k-tick latency distribution")
    st.add_argument("--ticks", default="100,1000,10000")
    st.add_argument("--out", default=None, help="output directory")
    st.add_argument("--formats", default="json,csv,md", type=lambda t: tuple(t.split(",")))
    st.set_defaults(func=_cmd_stress)

    c = sub.add_parser("compare", help="regression comparison of two runs")
    c.add_argument("baseline")
    c.add_argument("current")
    c.add_argument("--tolerance", type=float, default=5.0, help="percent")
    c.add_argument("--out", default=None, help="write Markdown to this path")
    c.set_defaults(func=_cmd_compare)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
