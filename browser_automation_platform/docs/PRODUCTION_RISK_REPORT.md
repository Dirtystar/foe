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

1. **Vision runs inline on the event loop.** `VisionPipeline` awaits analyzers
   directly. Real OCR/template matching is CPU-bound and will block the single
   event loop, delaying *all* sessions' ticks (the "slow session" test only
   passes because a hung session *awaits*; a CPU-bound one would stall the
   loop). The architecture already anticipates this: analyzers should offload
   to a `ProcessPoolExecutor`/`run_in_executor`. **Next scaling fix.** Not done
   here because it changes the vision execution model and needs its own
   validation.

2. **Recovery pauses the whole scheduler.** Under the live scheduler,
   `recover_session` stops and restarts the entire scheduler (the Scheduler
   forbids per-job mutation while running). One session's recovery briefly
   pauses all others. Harmless at low recovery rates and ≤8 sessions, but under
   high failure density it causes global thrash. Fix would be dynamic per-job
   add/remove inside the Scheduler — deferred to avoid changing a validated
   component.

3. **Writer queue is unbounded.** The persistence queue can grow to the full
   burst size if the enqueue rate exceeds the drain rate (observed peak 4791
   under an unthrottled test driver). It drains to 0 in realistic,
   interval-spaced operation and always flushes on `close()`, so it does not
   grow *indefinitely* in steady state — but a sustained overload (tiny
   intervals, very many tabs, or a stalled disk) would grow memory. Mitigation
   in place: `pending_writes` and write-latency are now observable via
   `SqliteStateStore.stats()`; operators should alarm on `pending`. A bounded
   queue with an explicit drop-or-block policy is the fix if this ever
   materialises (deferred — it trades data loss vs. backpressure and needs a
   product decision).

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

1. Offload CPU-bound vision analyzers off the event loop (risk #1) — the real
   throughput ceiling for multi-session real-browser operation.
2. Dynamic per-job scheduler mutation to remove the recovery global-pause
   (risk #2) — needed before high-failure-density or >16-session operation.
3. Bounded/backpressured persistence queue (risk #3) — needed only for
   sustained-overload or very-high-cardinality deployments.
4. Real-browser resource benchmarking at 8/16 tabs (RAM/CPU) — the practical
   deployment limit, outside the deterministic harness.
