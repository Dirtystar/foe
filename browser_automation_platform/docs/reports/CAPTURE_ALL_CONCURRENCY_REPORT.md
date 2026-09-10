# Capture All — Concurrency Fix (P0)

_Observe-only. No detector/classifier/OCR/threshold/weakening/cursor/scheduler change;
outputs are byte/semantically identical to the previous synchronous pipeline._

## 1. Root cause (measured)

**Capture All ran the entire per-World pipeline synchronously on the Qt GUI thread.**
`ForgeCollectionWindow._capture` looped over the selected Worlds and, for each,
called the CDP screenshot **and** `capture_frame` → `build_scan` (detector +
classifier) + `add_frame` (PNG encode/write). `QApplication.processEvents()` ran only
at the start/end of the loop, so the event loop never ticked during the work → the
window could not be moved, scrolled, or cancelled and Windows marked it
**Not Responding**.

Call chain that executed on the GUI thread:

```
Capture All → _capture (loop)
  → _capture_image(world)            # CDP screenshot (I/O)
  → capture_frame(image, …)
       → build_scan()                # BadgeDetector.scan + PercentClassifier  ← CPU
       → add_frame()                 # cv2.imencode + imwrite + labels.json     ← I/O+CPU
  → (repeat for every World)
  → refresh()                        # dataset_statistics/status_summary → load_all()  ← CPU/I/O
```

Measured on the committed corpus (`profile_capture.py`, warm):

| stage | time / World |
|---|---|
| `build_scan` (detector + classifier) | **3038 ms** |
| `capture_frame` (scan + dataset write) | **3013 ms** |
| **8 Worlds, synchronous** | **≈ 24 s of frozen GUI** (plus CDP capture) |

The final `refresh()` added another block: `dataset_statistics` and `status_summary`
each call `load_all()` (reads every reviewed frame from disk) — **2799 ms** and
**2641 ms** — i.e. `refresh()` alone stalled the GUI ~5.4 s. OpenCV ran with 4
internal threads (`cv2.getNumThreads()==4`), explaining the 44 % Python / 85–90 %
system CPU.

## 2. Concurrency architecture chosen — a single bounded worker thread

**Decision: run the whole batch on ONE background `QThread` worker, sequentially
(browser-capture concurrency 1, CPU-analysis 1 by default).** Justification measured,
not assumed:

- **OpenCV releases the GIL** during its heavy native ops (template matching, colour,
  resize). Empirically (`gil_test.py`): a worker thread ran **4× `build_scan`
  (11.4 s)** while a simulated GUI thread ticked every ~5 ms with a **max gap of
  10 ms**. So a single background thread genuinely offloads the CPU work and the Qt
  event loop keeps ticking — no multiprocessing required.
- **`concurrent.futures`/QThreadPool** would add nothing here: the bottleneck is one
  long CPU task per World and the machine is already at 85–90 % CPU, so the goal is
  *responsiveness, not throughput*. Running Worlds in parallel would raise CPU and
  hurt responsiveness.
- **ProcessPool/multiprocessing was rejected**: it would force pickling full-frame
  images across the process boundary and **cannot hold a browser `Page`/CDP context**
  in a child process (the spec forbids serialising a Page). The CDP screenshot already
  runs as a cross-thread `Future` with a **20 s timeout** (`service.capture_world(...)
  .result(timeout=20)`), so it is safe to call from the worker thread.

The GUI thread now does **presentation only**. The worker emits a `WorldProgress`
per stage via Qt **queued signals**; the GUI updates from those. No `QObject`/widget
is touched from the worker (it holds only the job and emits signals). The
detector/classifier/dataset code is imported and called **unchanged** — the async
job's default analyzer produces byte/semantically identical dataset results (proved by
a parity test).

Additional fix: the heavy **corpus-statistics refresh** (`load_all()`) was also moved
to a short-lived background thread (`_StatsWorker`), because it too blocked the GUI
~5.4 s on every refresh/filter change. Per-World updates now do only a light queue
refresh; the full statistics compute once at job finish, off-thread.

## 3. Pipeline (bounded, staged)

`bap.forge.collection.capture_job.CaptureJob.run()` per World, sequentially:

`WAITING → CAPTURING` (CDP screenshot, I/O) `→ ANALYSING` (detector/classifier off the
GUI thread) `→` atomic dataset write `→ COMPLETED | SKIPPED(duplicate) | FAILED`, then
the next World. If cancelled, the remaining Worlds are marked `CANCELLED` and never
started. The detector + classifier are built **once per batch** and reused (the old
path rebuilt the classifier bank per World).

**Bounded concurrency:** browser capture 1, CPU analysis 1. An **Analysis threads**
setting caps OpenCV's internal threads (`cv2.setNumThreads`): **1 (responsive,
default)** / 2 / Auto — so `workers × cv2-threads` can't oversubscribe an already-busy
machine.

## 4. Responsive progress UI

The window stays fully responsive. During a batch it shows a live line
`[3/8] H: analysing (2.1s)`, per-World completion in the log with duration and
det/cls/UNK, and the **queue refreshes after every completed World** (not only at the
end). Running totals appear in the finish summary. A visible **Cancel Capture** button
and an **Analysis threads** selector sit next to Capture All.

## 5. Cancellation

`Cancel Capture` is **cooperative**: it stops scheduling new Worlds immediately, lets
the in-flight World's atomic write finish (no partial image/label), keeps every
completed result, returns the UI to a usable state, and reports e.g.
*“Cancelled after 3 / 8 Worlds — 3 result(s) preserved.”* Closing the window during a
run asks **Cancel capture and close / Keep running / Stay open** — workers are never
silently abandoned.

## 6. Error containment

A per-World failure never aborts the batch. Each failure records
`{world, stage, type, reason, fix}` (e.g. `capture / timeout / "capture exceeded 20s" /
"Re-attach the World…"`) and the batch continues. Worker exceptions are caught and
returned to the GUI as a failed result — they never kill the process. Browser capture
carries the existing 20 s CDP timeout; any raise (timeout/detach) surfaces as a
contained `FAILED` with a recovery suggestion.

## 7. CPU & memory control

`cv2.setNumThreads` is set from the Analysis-threads setting (default **1**) before
processing, so the app does not use all cores by default. One analysis worker × a
small OpenCV cap keeps the machine responsive. Peak memory is unchanged (one frame in
flight at a time; images are never pickled or duplicated across processes).

## 8. Session recovery

The session persists batch state after every World: `batch = {requested, done, failed,
cancelled, running}` written atomically. If BAP crashes/closes mid-batch, completed
captures are already in the canonical dataset, and reopening shows a **Resume
Unfinished (N)** button that captures **only** the Worlds that did not finish —
completed Worlds are never re-captured.

## 9. Before / after (measured)

| metric | before | after |
|---|---|---|
| GUI-thread block during 8-World Capture All | **≈ 24 s** (frozen) | **~0** (returns in ~4 ms; batch off-thread) |
| GUI event-loop max tick gap during a batch | window frozen | **48 ms** (median 10 ms) |
| GUI block on the finish/stats refresh | ~5.4 s | off-thread (light queue update only) |
| classifier builds per 8-World batch | 8 | **1** |
| detector/classifier outputs | baseline | **identical** (parity test) |

## 10. Tests

- **`tests/unit/forge/test_capture_job.py`** (Qt-free, 8): per-World progress in order;
  capture is strictly sequential (max concurrency 1); cancel stops future Worlds and
  preserves completed; a capture failure and an analyze exception are each contained;
  capture **timeout** is reported; `cv2.setNumThreads` is bounded; the default analyzer
  matches synchronous `capture_frame`.
- **`tests/unit/gui/test_capture_async.py`** (offscreen Qt, 7): Capture All returns to
  the event loop immediately; **a QTimer keeps ticking (max gap < 400 ms) while a slow
  fake batch runs**; repeated Capture All cannot overlap; cancel stops future Worlds;
  closing during capture honours the chosen action; the worker holds no widget
  reference; session recovery resumes only unfinished Worlds.
- Existing collection/review GUI tests updated to pump the loop for the async path.
- Full unit suite: see the commit (all green).

## 11. Windows verification checklist

1. Attach 8 Worlds; set browser mode External Chromium.
2. Open Live Data Collection; Start Session.
3. Click **Capture All Worlds** (or `Ctrl+Enter`).
4. **Move and resize** the window during processing.
5. **Scroll** the queue.
6. **Switch filters** and sort.
7. Confirm Windows never shows **Not Responding**.
8. Click **Cancel Capture** after several Worlds; confirm the summary
   “Cancelled after k / 8 — k preserved”.
9. Confirm the completed frames remain in the dataset (queue + Datasets stats).
10. Click **Resume Unfinished** and confirm only the remaining Worlds capture.
11. Run the full 8-World batch to completion.
12. Record total duration, per-World duration (shown in the log), and peak CPU/memory.

**Acceptance:** GUI responsive throughout · Cancel works · results appear
incrementally · completed results never lost · one failed World doesn't abort the
batch · no duplicate/corrupt dataset entry · output matches the synchronous pipeline.

## 12. Known limitations

- Real Windows testing was **not possible in this environment** (headless Linux, no
  attached Chrome). Responsiveness is proven on Linux with an offscreen Qt event-loop
  tick monitor and a GIL-release measurement; the CDP capture path is unchanged and
  already carries a 20 s timeout. The §11 checklist is provided for the operator.
- Cancellation is cooperative: the **currently-analysing** World finishes (bounded by
  its ~3 s analysis and the 20 s capture timeout) before the batch stops — by design,
  so no partial data is written.
- "Analysis threads" bounds OpenCV's internal threads; Worlds are still processed one
  at a time (throughput is intentionally traded for responsiveness on a busy machine).
- The background statistics refresh reads the whole corpus with `load_all()`; it is
  off-thread now, but a very large future corpus may warrant caching (out of scope).
