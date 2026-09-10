"""Export benchmark results to JSON, CSV, and a Markdown report (Milestone 4.9).

Presentation only — these serialize a `BenchmarkResult` (or its dict) into
portable, diffable artifacts. JSON is the source of truth (and the input to
regression comparison); CSV is spreadsheet-friendly; Markdown is a human report.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path


def _as_dict(result) -> dict:
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def to_json(result, *, indent: int = 2) -> str:
    return json.dumps(_as_dict(result), indent=indent, sort_keys=True)


_METRIC_COLS = ["count", "mean", "median", "p95", "p99", "worst", "min", "stdev", "fps"]


def to_csv(result) -> str:
    """A flat CSV: one row for the global summary, one per stage, one per World."""
    d = _as_dict(result)
    buf = io.StringIO()
    writer = csv.writer(buf)
    unit = d.get("global", {}).get("unit", "ms")
    writer.writerow(["scope", "name", *[f"{c}_{unit}" if c not in ("count", "fps") else c
                                        for c in _METRIC_COLS]])

    def row(scope: str, name: str, summ: dict) -> None:
        writer.writerow([scope, name, *[summ.get(c, "") for c in _METRIC_COLS]])

    row("global", d.get("label", "global"), d.get("global", {}))
    for stage, summ in d.get("stage_breakdown", {}).items():
        row("stage", stage, summ)
    for world, wsumm in d.get("worlds", {}).items():
        row("world", world, wsumm)
    return buf.getvalue()


def _fmt(summ: dict) -> str:
    return (f"{summ.get('mean', 0):.3f} | {summ.get('median', 0):.3f} | "
            f"{summ.get('p95', 0):.3f} | {summ.get('p99', 0):.3f} | "
            f"{summ.get('worst', 0):.3f} | {summ.get('fps', 0):.2f}")


def to_markdown(result) -> str:
    d = _as_dict(result)
    unit = d.get("global", {}).get("unit", "ms")
    lines: list[str] = []
    lines.append(f"# Performance report — {d.get('label', '')} ({d.get('kind', '')})")
    lines.append("")
    lines.append(f"- Created: `{d.get('created_at', '')}`  ·  git `{d.get('git_ref') or 'n/a'}`")
    m = d.get("machine", {})
    lines.append(f"- Machine: {m.get('platform', '')}  ·  {m.get('cpu_count', '?')} CPU  ·  "
                 f"Python {m.get('python', '')}")
    lines.append(f"- Frames replayed: {d.get('frames_used', '?')}  ·  config: `{d.get('config', {})}`")
    extra = d.get("extra", {})
    if extra:
        bits = "  ·  ".join(f"{k}={v}" for k, v in extra.items())
        lines.append(f"- {bits}")
    lines.append("")

    lines.append(f"## Global tick timing ({unit})")
    lines.append("")
    lines.append("| scope | mean | median | p95 | p99 | worst | fps |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(f"| **total** | {_fmt(d.get('global', {}))} |")
    for stage, summ in d.get("stage_breakdown", {}).items():
        lines.append(f"| {stage} | {_fmt(summ)} |")
    lines.append("")

    worlds = d.get("worlds", {})
    if worlds:
        lines.append(f"## Per-World timing ({unit})")
        lines.append("")
        lines.append("| world | ticks | skipped | mean | median | p95 | worst | fps | worst stage |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, w in worlds.items():
            lines.append(
                f"| {name} | {w.get('count', 0)} | {w.get('skipped_ticks', 0)} | "
                f"{w.get('mean', 0):.3f} | {w.get('median', 0):.3f} | {w.get('p95', 0):.3f} | "
                f"{w.get('worst', 0):.3f} | {w.get('fps', 0):.2f} | {w.get('worst_stage') or '-'} |")
        lines.append("")

    sysd = d.get("system", {})
    lines.append("## System")
    lines.append("")
    lines.append(f"- Uptime: {sysd.get('uptime_s', '?')} s  ·  backend: {sysd.get('backend', '?')}")
    lines.append(f"- CPU: avg {sysd.get('avg_cpu_percent', '?')}%  ·  peak "
                 f"{sysd.get('peak_cpu_percent', '?')}%  ·  {sysd.get('cpu_count', '?')} cores")
    lines.append(f"- RAM: avg {sysd.get('avg_ram_mb', '?')} MB  ·  peak "
                 f"{sysd.get('peak_ram_mb', '?')} MB  ·  current {sysd.get('current_ram_mb', '?')} MB")
    lines.append("")
    return "\n".join(lines)


def write_report(result, out_dir: Path | str, *, stem: str = "benchmark",
                 formats=("json", "csv", "md")) -> dict[str, str]:
    """Write the requested formats under `out_dir`. Returns {format: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    if "json" in formats:
        p = out / f"{stem}.json"; p.write_text(to_json(result), encoding="utf-8")
        written["json"] = str(p)
    if "csv" in formats:
        p = out / f"{stem}.csv"; p.write_text(to_csv(result), encoding="utf-8")
        written["csv"] = str(p)
    if "md" in formats:
        p = out / f"{stem}.md"; p.write_text(to_markdown(result), encoding="utf-8")
        written["md"] = str(p)
    return written


def write_suite(results, out_dir: Path | str, *, stem: str = "suite",
                formats=("json", "csv", "md")) -> dict[str, str]:
    """Write a combined report for a list of results (a sweep)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    payload = [_as_dict(r) for r in results]
    if "json" in formats:
        p = out / f"{stem}.json"
        p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        written["json"] = str(p)
    if "csv" in formats:
        p = out / f"{stem}.csv"
        p.write_text("\n".join(to_csv(r) for r in results), encoding="utf-8")
        written["csv"] = str(p)
    if "md" in formats:
        p = out / f"{stem}.md"
        p.write_text("\n\n---\n\n".join(to_markdown(r) for r in results), encoding="utf-8")
        written["md"] = str(p)
    return written


__all__ = ["to_json", "to_csv", "to_markdown", "write_report", "write_suite"]
