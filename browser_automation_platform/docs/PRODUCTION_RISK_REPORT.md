# Production Risk Report — Load & Stress Hardening

Scope: validate runtime behaviour under realistic workloads using the real
runtime wired to stub adapters (no architecture bypassed, no test-only hooks
in production code beyond added observability). Drivers are deterministic
(`run_once` + drained recovery) except where real-time scheduling is required.

Harness: `tests/loadkit.py`; scenarios in `tests/load/` and `tests/stress/`
(run with `-m load` / `-m stress`; deselected from the default suite).

---

## Summary

The platform is stable under the target workload (1–16 sessions). No memory,
thread, or asyncio-task leaks were found. Recovery is correctly isolated and
bounded. Persistence keeps up with realistic tick rates and flushes cleanly.

**One real defect was found and fixed:** `create_application` silently dropped
`on_report`/`sleep` when a pre-built `scheduler` was injected — it now raises
instead (`ValueError`). Two scaling risks are documented below as
known-and-monitored rather than fixed, because fixing them would require
architectural change disproportionate to current needs.

---

## Measured results (this environment)

| Scenario | Result |
|---|---|
| Throughput (stub, single event loop) | ~13–14k ticks/s, flat from 1→16 sessions |
| Fairness | Every session ticked exactly N times per N rounds — zero starvation |
| Memory growth (4000 ticks, 8 sessions) | −1 objects — no per-tick retention |
| Thread lifecycle (10 store open/close) | baseline 1 → 1 — every writer thread joined |
| asyncio tasks after shutdown | ≤ baseline — all job tasks terminated |
| Slow (hung) session | Other sessions kept ticking (cooperative loop holds) |
| Scheduler interval accuracy | Every requested sleep == configured interval (no scheduler-induced drift) |
| Jitter | interval + rng()·jitter exactly, bounded |
| Recovery isolation | 1 crashing session recovered; other 7 opened once, untouched |
| Recovery bound | Permanently-broken session recreated ≤3× then disabled |
| Disabled session | Stops ticking — no further tab opens or capture calls |
| Persistence volume | 4800 ticks + 4800 actions persisted, 0 lost, 0 failed |
| Write latency | avg 0.88 ms, max ~129 ms (first write / WAL checkpoint) |
| Writer queue | Drains to 0 between bursts and on `close()` |
| WAL | Enabled (concurrent-reader friendly) |
| Slow writer | Tick loop finished in <0.2s for 200 ticks while writer lagged — enqueue never blocks runtime |

---

## Tested limits

- **Concurrency:** validated 1, 4, 8, 16 concurrent sessions on one asyncio
  loop. Fairness and isolation hold at 16.
- **Volume:** 4800 ticks/actions persisted in one burst with zero loss.
- **Failure density:** a permanently-failing session and a transiently-failing
  session under an 8-session load; recovery stayed isolated and bounded.

These are validated *functional* limits with stub adapters — i.e. the
orchestration, recovery, persistence, and scheduling logic are correct at
these scales. They are **not** real-browser throughput numbers.

---

## Expected production limits

Real limits are set by the browser and vision work, not the orchestration:

- **Playwright/Chromium:** each real tab is ~tens–hundreds of MB RAM and real
  CPU for rendering + screenshots. 8 tabs is comfortable on a developer
  machine; 16+ depends on host RAM/CPU. This is the dominant constraint.
- **Vision:** OCR/template matching are CPU-bound (tens–hundreds of ms per
  frame). At 8 sessions capturing every ~500 ms, vision is the real
  throughput ceiling, and today it runs inline on the event loop (see risks).
- **Persistence:** SQLite comfortably absorbs the realistic rate (a few writes
  per second per session). At ~0.9 ms/write it sustains >1000 writes/s
  single-threaded — far above any realistic tick rate.

Practical guidance: **8 sessions at ≥300 ms intervals is the comfortable
production envelope** on a single machine; treat 16 as the upper bound pending
the vision-offload fix below.

---

## Identified bottlenecks / scaling risks (documented, not fixed)

1. ~~**Vision runs inline on the event loop.**~~ **FIXED.** `AsyncVisionPipeline`
   (`adapters/vision/async_pipeline.py`) offloads analyzer execution to a shared
   `ThreadPoolExecutor` (`create_application(vision_workers=N)`; default 4 with
   `--real-vision`). A drop-in subclass of `VisionPipeline`, so CaptureBinding,
   TabSession, and the analyzer port are unchanged. Measured: with one blocking
   (20 ms) analyzer, a co-scheduled fast session ticked **20× inline vs 700×
   offloaded** in the same 0.4 s window. Threads are joined on `Application.stop`
   (`shutdown(wait=True)`). Note: still thread-based, so genuinely parallel
   CPU work is bounded by the GIL for pure-Python analyzers — cv2/tesseract
   release the GIL during native work, so real OCR/template matching parallelise;
   a `ProcessPoolExecutor` variant is the next step only if a pure-Python
   analyzer becomes the bottleneck.

2. ~~**Recovery pauses the whole scheduler.**~~ **FIXED.** The Scheduler now
   supports safe runtime job mutation — `register_job` / `unregister_job` /
   `replace_job` operate while it keeps ticking, each job running in its own
   task with a per-job cancel event so cancellation interrupts only the *sleep*,
   never an in-flight *tick*. `SessionManager.recover_session` now uses
   `replace_job` (no stop/start), and create/close use register/unregister — so
   no runtime lifecycle operation pauses the scheduler. Verified: recovery
   (single and 4-way concurrent) while running never stops the scheduler; a
   16-session live-scheduler run with continuous periodic failures kept every
   session ticking (15–16 ticks each, no starvation), recovered the flaky
   sessions repeatedly, and the scheduler never paused. Invariants covered by
   tests: in-flight tick finishes normally on removal, no second tick after
   removal, no duplicate/lost jobs under concurrent replacement, fairness
   preserved across replacement, failed replacement leaves a consistent state.

3. ~~**Writer queue is unbounded.**~~ **FIXED.** The write buffer is now bounded
   (`SqliteStateStore(max_queue_size=N)`, default 10 000) with a non-blocking,
   priority-aware overload policy: the runtime never blocks on storage, and when
   the buffer is full, records are dropped lowest-priority-first (LOW successful
   history → NORMAL action successes → IMPORTANT failures), while CRITICAL
   health/recovery events bypass the bound and are never dropped. `stats()` now
   exposes `pending`, `dropped`, `overloaded`, and write latency. Verified under
   a 16-session load against a 50-slot buffer + slow writer: 3200 ticks
   enqueued, ~3142 dropped by priority, **every session still completed all
   ticks**, and written+dropped reconciled exactly (no silent loss).
   **Tradeoff:** under sustained overload, low-priority tick *history* is
   sacrificed to keep the runtime responsive and the diagnostic
   (health/failure) record intact — a deliberate lossy-telemetry choice, not
   backpressure. The residual risk is a sustained flood of CRITICAL records
   (bypasses the bound); bounded in practice by how often health transitions
   occur.

4. **WAL checkpoint latency spikes.** Max write latency (~129 ms) corresponds
   to WAL setup / autocheckpoint, versus ~0.9 ms typical. Not a correctness
   issue; if it matters, tune `wal_autocheckpoint` or checkpoint on a timer.

---

## Fix applied

- **`create_application` mutually-exclusive scheduler vs on_report/sleep.**
  Passing a pre-built `scheduler` together with `on_report` or `sleep`
  previously dropped the latter silently (the injected scheduler kept its own
  config), so reports never reached the sink. Now raises `ValueError`. Found by
  the scheduler-validation harness; covered by a unit test.

- **Persistence observability added** (`SqliteStateStore.stats()` /
  `pending_writes`) — required to measure the persistence-stress scenario and
  to monitor risk #3 in production.

No other production code was changed: the load/stress work is otherwise pure
test harness over existing ports.

---

## Next scaling risks (in priority order)

1. ~~Offload CPU-bound vision analyzers~~ — **done** (AsyncVisionPipeline). A
   `ProcessPoolExecutor` variant remains a future option if a *pure-Python*
   analyzer (not GIL-releasing cv2/tesseract) becomes the bottleneck.
2. ~~Dynamic per-job scheduler mutation~~ — **done** (register/unregister/
   replace while ticking; recovery no longer pauses the scheduler).
3. ~~Bounded/backpressured persistence queue~~ — **done** (bounded + priority
   dropping). A future refinement could make dropped-priority thresholds
   configurable per deployment.
4. Real-browser resource benchmarking at 8/16 tabs (RAM/CPU) — **now
   observable**: browser resource monitoring (memory/CPU/pages/contexts) is
   collected via a `BrowserMetricsPort`, persisted to a `browser_metrics`
   table, shown on the dashboard, and enforced against configurable limits
   that raise `RESOURCE_PRESSURE` (a browser-level health signal driving a
   bounded degrade → recover → disable policy). Memory/CPU require the
   `monitoring` extra (psutil); without it, page/context counts still work and
   memory/CPU report None. What remains is establishing *deployment-specific*
   limits from real hardware — a tuning exercise, not a code gap.

---

## Resource monitoring (this milestone)

- **Observational-first, adapter-isolated.** `BrowserMetricsPort.collect()`
  returns a generic `BrowserResourceSnapshot` (no Playwright/Chromium types in
  core). The Playwright adapter reads page/context counts from the browser and
  memory/CPU best-effort via psutil over the Chromium process tree; a missing
  process or absent psutil yields None, never an error.
- **Rides the existing report stream.** A `ResourceMonitor` sits in the report
  sink chain (like Supervisor/PersistenceSink), forwards every report, and uses
  the report cadence to trigger periodic collection *off* the callback — no
  TabSession change, no second event system. Measured: monitoring adds
  negligible tick-throughput overhead (0.137s vs 0.135s baseline over 200
  rounds × 8 sessions; 16 sessions monitored show no starvation).
- **Bounded pressure policy.** Limits (`max_memory_mb`, `max_pages`) are
  evaluated per snapshot; breaches feed a `ResourcePressurePolicy` in the
  Supervisor that degrades on brief pressure, recovers all sessions once at a
  sustained threshold, and disables them only if pressure persists — it never
  kills the browser directly.
- **Residual risk:** memory attribution is browser-global (not per-tab), so the
  recover/disable actions are coarse (all sessions). Per-tab memory attribution
  (CDP per-target metrics) would allow targeting the heaviest tab — a future
  refinement, not required for safe operation.
