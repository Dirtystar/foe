"""Regression comparison between two benchmark runs (Milestone 4.9).

Compares a *current* run against a *baseline* (e.g. this branch vs the numbers
captured on tag ``forge-m4-stable``) and classifies each metric as a regression,
an improvement, or unchanged. Lower-is-better for latency metrics (mean, median,
p95, p99, worst); higher-is-better for throughput (fps). A metric only counts as
changed when it moves more than `tolerance` (default 5%), so normal run-to-run
system variance is not reported as a regression.
"""

from __future__ import annotations

from dataclasses import dataclass

# Latency metrics where a smaller value is better.
_LOWER_BETTER = ("mean", "median", "p95", "p99", "worst")
# Throughput where a larger value is better.
_HIGHER_BETTER = ("fps",)


def _as_dict(run) -> dict:
    return run.to_dict() if hasattr(run, "to_dict") else dict(run)


def _pct_change(base: float, cur: float) -> float | None:
    if base == 0:
        return None
    return (cur - base) / abs(base) * 100.0


@dataclass
class MetricDelta:
    metric: str
    baseline: float
    current: float
    pct_change: float | None
    verdict: str          # "regression" | "improvement" | "unchanged" | "n/a"

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "pct_change": round(self.pct_change, 2) if self.pct_change is not None else None,
            "verdict": self.verdict,
        }


def _classify(metric: str, base: float, cur: float, tolerance: float) -> MetricDelta:
    pct = _pct_change(base, cur)
    if pct is None:
        return MetricDelta(metric, base, cur, None, "n/a")
    higher_better = metric in _HIGHER_BETTER
    improved = (cur > base) if higher_better else (cur < base)
    if abs(pct) <= tolerance:
        verdict = "unchanged"
    elif improved:
        verdict = "improvement"
    else:
        verdict = "regression"
    return MetricDelta(metric, base, cur, pct, verdict)


def compare_summaries(baseline: dict, current: dict, *, tolerance: float = 5.0) -> list[MetricDelta]:
    """Compare two Summary.to_dict() blocks across the standard metrics."""
    deltas: list[MetricDelta] = []
    for metric in (*_LOWER_BETTER, *_HIGHER_BETTER):
        if metric in baseline and metric in current:
            deltas.append(_classify(metric, float(baseline[metric]), float(current[metric]), tolerance))
    return deltas


@dataclass
class Comparison:
    baseline_label: str
    current_label: str
    tolerance: float
    global_deltas: list[MetricDelta]
    stage_deltas: dict[str, list[MetricDelta]]

    @property
    def regressions(self) -> list[MetricDelta]:
        return [d for d in self._all() if d.verdict == "regression"]

    @property
    def improvements(self) -> list[MetricDelta]:
        return [d for d in self._all() if d.verdict == "improvement"]

    def _all(self) -> list[MetricDelta]:
        out = list(self.global_deltas)
        for ds in self.stage_deltas.values():
            out.extend(ds)
        return out

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline_label,
            "current": self.current_label,
            "tolerance_percent": self.tolerance,
            "global": [d.to_dict() for d in self.global_deltas],
            "stages": {name: [d.to_dict() for d in ds] for name, ds in self.stage_deltas.items()},
            "regression_count": len(self.regressions),
            "improvement_count": len(self.improvements),
        }


def compare(baseline, current, *, tolerance: float = 5.0) -> Comparison:
    """Compare two `BenchmarkResult`s (or their dicts)."""
    b, c = _as_dict(baseline), _as_dict(current)
    stage_deltas: dict[str, list[MetricDelta]] = {}
    b_stages, c_stages = b.get("stage_breakdown", {}), c.get("stage_breakdown", {})
    for stage in sorted(set(b_stages) & set(c_stages)):
        stage_deltas[stage] = compare_summaries(b_stages[stage], c_stages[stage], tolerance=tolerance)
    return Comparison(
        baseline_label=b.get("label", "baseline"),
        current_label=c.get("label", "current"),
        tolerance=tolerance,
        global_deltas=compare_summaries(b.get("global", {}), c.get("global", {}), tolerance=tolerance),
        stage_deltas=stage_deltas,
    )


def _arrow(verdict: str) -> str:
    return {"regression": "🔺 regression", "improvement": "🔻 improvement",
            "unchanged": "· unchanged", "n/a": "n/a"}.get(verdict, verdict)


def to_markdown(cmp: Comparison) -> str:
    lines = [f"# Regression comparison — `{cmp.current_label}` vs baseline `{cmp.baseline_label}`", ""]
    lines.append(f"Tolerance: ±{cmp.tolerance:.0f}%  ·  "
                 f"**{len(cmp.regressions)} regression(s), {len(cmp.improvements)} improvement(s)**")
    lines.append("")
    lines.append("## Global")
    lines.append("")
    lines.append("| metric | baseline | current | Δ% | verdict |")
    lines.append("|---|---|---|---|---|")
    for d in cmp.global_deltas:
        pct = f"{d.pct_change:+.1f}%" if d.pct_change is not None else "n/a"
        lines.append(f"| {d.metric} | {d.baseline:.3f} | {d.current:.3f} | {pct} | {_arrow(d.verdict)} |")
    lines.append("")
    if cmp.stage_deltas:
        lines.append("## Stages")
        lines.append("")
        lines.append("| stage | metric | baseline | current | Δ% | verdict |")
        lines.append("|---|---|---|---|---|---|")
        for stage, ds in cmp.stage_deltas.items():
            for d in ds:
                if d.verdict in ("unchanged", "n/a"):
                    continue
                pct = f"{d.pct_change:+.1f}%" if d.pct_change is not None else "n/a"
                lines.append(f"| {stage} | {d.metric} | {d.baseline:.3f} | {d.current:.3f} | "
                             f"{pct} | {_arrow(d.verdict)} |")
        lines.append("")
    return "\n".join(lines)


__all__ = ["MetricDelta", "Comparison", "compare", "compare_summaries", "to_markdown"]
