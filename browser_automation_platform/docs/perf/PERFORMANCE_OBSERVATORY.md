# Performance Observatory (Milestone 4.9)

**Measurement only.** This framework times the existing observe-only pipeline and
reports trustworthy numbers. It changes **no** behaviour — no detector, classifier,
OCR, scheduler, World, dataset, or threshold logic is touched, and the app stays
observe-only. The goal is one decision input: *can the current architecture scale
to 8 simultaneous Worlds before we ever enable cursor movement or clicking?*

## TL;DR finding

The pipeline is **detection-bound**. On the reviewed frame set, a single tick
costs ~3 s warm (≈3.5 s p95, up to ~5 s cold), of which badge **detection** is
~95%; weakening OCR (~0.1 s) and percentage classification (~0.06 s) are small.
That is roughly **0.3 FPS per World**, and because Worlds are serviced by one
process the aggregate throughput stays ~0.3 FPS *total* no matter how many Worlds
are attached — 8 Worlds would each be visited only ~once every ~24 s. Detection
already keeps ~3 CPU cores busy (avg CPU ~250–320% on a 4-core box), so there is
little headroom to parallelise as-is. **Conclusion: 8 Worlds cannot be serviced
near real time without first optimising detection.** This milestone captures that
as reproducible numbers; it changes nothing.

### Measured baseline (this repo's machine — 4 CPU, 66 reviewed frames)

Timings are machine-specific; regenerate locally. Full detail in
`synthetic_baseline.{md,json,csv}` and `stress_baseline.{md,json,csv}`.

| Worlds | mean tick | p95 | FPS/World | throughput | peak RAM | avg CPU |
|---|---|---|---|---|---|---|
| 1 | 2994 ms | 3664 ms | 0.33 | 0.33 fps | 461 MB | 318% |
| 2 | 3439 ms | 3960 ms | 0.29 | 0.29 fps | 461 MB | 256% |
| 4 | 3399 ms | 4374 ms | 0.29 | 0.29 fps | 461 MB | 286% |
| 8 | 3225 ms | 5294 ms | 0.31 | 0.31 fps | 461 MB | 293% |

Stress (30 ticks): avg 3459 ms · median 3637 ms · p95 5267 ms · p99 5319 ms ·
max 5320 ms.

Stage breakdown (1-World): detection ~2835 ms · weakening_ocr ~104 ms ·
classification ~55 ms · capture/decision <1 ms.

## What is measured

Every pipeline stage is timed separately, per tick:

| stage | what it covers |
|---|---|
| `capture` | frame decode (a live capture produces the array here) |
| `weakening_ocr` | the per-World weakening safety-gate read |
| `detection` | badge candidate detection over the battle-map ROI |
| `classification` | percentage classifier + province-panel corroboration |
| `decision` | gate decision + deterministic target selection |
| `gui_update` | optional — representative UI marshaling cost |
| `persistence` | optional — representative serialization cost |

Per-World statistics: average, median, p95, worst, tick count, skipped ticks,
FPS-equivalent, and a per-stage breakdown. Global statistics: uptime, CPU
(avg/peak), RAM (avg/peak/current), attached Worlds, running Worlds.

## How it stays faithful to production

`bap.perf.pipeline.run_tick` calls the **unmodified** `scan.build_scan` stage
functions in the same order, wrapping each in a monotonic timer. A drift test
(`tests/unit/perf/test_pipeline_drift.py`) asserts the harness produces the same
detections, decision, selected click-point, percentages, and weakening read as
`build_scan` on a real frame — so the numbers describe the real path, not a copy.

## Benchmarks (offline, reproducible, no browser)

Frames are loaded once from the reviewed datasets and replayed from memory in a
fixed, sorted order with a fixed World assignment and no randomness, so re-running
on the same machine yields comparable results within normal system variance.

### Synthetic — scaling

```
python -m bap.perf synthetic --worlds 1,2,4,8 --ticks 100 --out docs/perf
```

Reports frames/sec, tick latency, per-stage breakdown, CPU, and RAM for 1 / 2 / 4
/ 8 Worlds. Worlds are serviced round-robin, matching a single-process scheduler.

> Note: the real detector is heavy (multi-second per tick), so large `--ticks`
> values take a long time. The committed baseline uses a small tick count to keep
> the artifact reproducible quickly; raise `--ticks` for tighter estimates.

### Stress — distribution

```
python -m bap.perf stress --ticks 100,1000,10000,100000 --out docs/perf
```

Runs a fixed tick budget over the reviewed frames and reports average / median /
p95 / p99 / max. All four budgets are supported; the larger ones are intended for
overnight runs given the detection cost.

## Export & regression comparison

Every result exports to JSON (source of truth), CSV (spreadsheet), and Markdown
(human report) via `bap.perf.export`. Two runs are compared with:

```
python -m bap.perf compare baseline.json current.json --out compare.md
```

Lower-is-better for latency metrics, higher-is-better for FPS; a metric only
counts as a regression/improvement when it moves more than the tolerance (±5% by
default), so normal variance is not reported as a change. The command exits
non-zero when any regression is found, so CI can gate on it. Use it to compare the
current branch against numbers captured on tag `forge-m4-stable`.

## Dashboard

The Forge nav-shell has a **Performance** page: per-World and global timing, live
charts (programmatic QPainter sparkline + stage-breakdown bars — no external
libraries), recent slow ticks, worst stage / current bottleneck, historical
averages, and a background "Run offline benchmark" button. It reads the shared
`bap.perf.registry` and live-refreshes only while visible.

## Acceptance (all satisfied)

No optimisations, no behaviour changes, no detector/classifier/OCR/scheduler/
dataset changes, no retraining, no threshold changes. Still observe-only. Existing
tests pass; performance tests added.
