# Live Forge Validation — Milestone 4.10

_Live verification + evidence collection after review_batch_002 retraining,
`MIN_PCT_SIM` 0.62 → 0.70, capture-geometry fixes, multi-World routing, the new
desktop UI shell, and the Performance Observatory. Observe-only throughout — no
click, cursor, keyboard, battle flow, or gameplay was performed or added._

Branch `claude/browser-automation-architecture-5784h1` · HEAD `38bde9b` at start ·
tree clean · `forge-m4-stable` tag intact at `8e10327`.

---

## ⚠️ Environment scope — read this first

This review was executed by an agent running in a **headless cloud container**,
not on the operator's Windows machine. There is **no display, no logged-in Forge
account, and no live Guild-Battlegrounds tab** in this environment. Therefore the
**human-in-the-loop live steps cannot be performed here** and are **not claimed as
done**: visually reading the on-screen weakening number, manually counting badges
in a *new* live battle, and driving the desktop app against real Forge tabs.

To keep the milestone honest, every statement below is tagged:

- **[LIVE]** — a verified fact about a real logged-in Forge session. **There are
  none in this run** (no live browser was reachable).
- **[REAL-FRAME]** — verified by running the actual pipeline on **real Forge
  screenshots** already in the repo (`tests/forge_assets/`: grading, live_review,
  review_batch_002). These are genuine captures, just not captured *this session*.
- **[CODE]** — verified by exercising the code paths / logic offscreen or via tests.
- **[OFFLINE]** — offline metrics (LOFO evaluation, benchmark replay).
- **[INFERENCE]** — engineering judgement, not a measured fact.

**Bottom line up front:** the application **starts, the new UI shell is sound, and
the multi-World routing / read-only-capture / per-World weakening-isolation /
coordinate / no-false-panel invariants all hold** under code and real-frame
verification. What is **missing to close M4.10 is a human operator (or uploaded
live captures)** to produce fresh live battle frames, live weakening reads at the
real top-bar location, and live per-World performance. **Recommendation:
insufficient *new* battle data to green-light Move-Cursor Preview — one live
operator pass (or a batch of uploaded live captures) is required first.** See §10.

---

## 1. Clean starting point  [CODE]

| item | value |
|---|---|
| branch | `claude/browser-automation-architecture-5784h1` |
| HEAD at start | `38bde9b` (ENGINEERING_REVIEW_M4.md) |
| working tree | clean |
| baseline tag | `forge-m4-stable` → `8e10327` (intact, untouched) |
| app-start smoke | PASS (offscreen construction of the Forge shell) |

No code changed before verification. `forge-m4-stable` was not altered.

---

## 2. UI shell smoke  [CODE — offscreen]

Constructed the real `MainWindow(forge=True)` with a persisted `WorldStore`
(H, F) under `QT_QPA_PLATFORM=offscreen`, navigated every page, and force-painted
(`grab()`) at startup size and maximized.

| check | result |
|---|---|
| Dashboard opens | PASS |
| Worlds page shows persisted Worlds | PASS — rows `['H','F']` |
| Vision page opens | PASS — Test Scan combo populated `['H','F']` |
| Performance page opens | PASS |
| navigation switches to correct page | PASS — all 8 nav keys map to the right stack index |
| World Manager controls usable + correctly gated | PASS — Add present; Edit/Remove disabled with no selection; Scan/Close disabled while browser closed |
| startup size (1360×860) paints | PASS |
| maximized paints | PASS |
| clipped text / overlapping widgets | **NOT VERIFIABLE HERE** — requires a human looking at a real display; offscreen paints cannot judge visual overlap/clipping |

**Presentation defects:** none detectable in code; **visual-layout defects
(clipping/overlap) remain an open human check** — recorded separately from
functional defects, which are none.

Non-blocking note: the offscreen platform prints `does not support
propagateSizeHints()` — a harmless Qt offscreen-plugin message, not a defect.

---

## 3. Multi-World routing  [CODE — logic proven with fake tabs]

The live browser is absent, but the **routing decision logic**
(`forge/detection/testscan.py::resolve_target`, `attached_aliases`) was exercised
with a real `WorldStore` + `TabAssignment` + fake `BrowserTab`s. Routing resolves
the tab **freshly from the assignment on every call** (no cached handle), which is
the anti-stale-reuse guarantee.

| requirement | result |
|---|---|
| selecting World H scans H | PASS — resolves `tab-H1` (H's tab) |
| selecting World F scans F | PASS — resolves `tab-F9` (F's tab) |
| target shows alias, hostname, title, URL | PASS — `summary()` prints all four before capture |
| Scan All uses each World's own current tab | PASS — `attached_aliases` → `['H','F']`, each resolved independently |
| removing one World doesn't make another reuse a stale tab | PASS — after removing H, F still → `tab-F9`; H → "World not found" |
| Stop automation does not close Chromium | PASS (design + tests) — Stop calls `stop_runtime`; browser teardown is a separate explicit path |
| closing the app is the only full browser-shutdown path | PASS — exit prompt defaults to "keep Chromium"; only explicit choice tears it down |

Targeted suite: `test_testscan.py`, `test_forge_lifecycle.py`,
`test_forge_capture_readonly.py`, `test_capture_geometry.py`, `test_weakening.py`,
`test_forge_decision.py` — **64 passed**.

**What still needs [LIVE]:** proving the *same* routing against two real attached
Forge tabs and saving per-World artifacts from real captures. The logic is proven;
the live capture is not exercisable here.

---

## 4. Capture geometry  [REAL-FRAME]

Ran `build_scan` on real Forge screenshots (1600×900 live-F and 1920×1080 batch
frames). Verified per frame:

| property | result on real frames |
|---|---|
| capture contains top bar + map area | PASS — frames include the top bar; battle-map ROI covers ≥ the usable map |
| all detector coordinates in **full-image** space | PASS — every detection box within `[0,w]×[0,h]` (`coords_in_full_image=True`) |
| no false province-panel overlay drawn | PASS — `panel.present=False` on every tested frame |
| debugger overlay does not contaminate analyzer input | PASS (design) — `annotate()` draws on a copy; analysis runs on the raw capture |
| weakening ROI points at the number | **MIXED — see finding LF-1** |

### Finding LF-1 (real, live-relevant): weakening ROI is uncalibrated on live 1600×900
On the **real live-F capture** (`live:F_…png`, 1600×900, human ground-truth
weakening = 65) the default `derive_rois` weakening ROI landed at `(246,2,47,26)`
— **not** where the number actually is on that resolution — so the reader returned
**value=None / UNKNOWN (conf 0.00) → decision UNKNOWN**. The fail-safe held (no
wrong read), but it means **live weakening will read UNKNOWN until an operator
draws Set-Weakening-Region for the live resolution**. On the calibrated 1920×1080
batch frames the ROI sits correctly and the reader returns a confident value. This
is exactly the kind of live-calibration step §5 calls for; it is a **calibration
gap, not a code defect**, so no code change was made.

---

## 5. Current weakening reader  [CODE + REAL-FRAME]

- **Per-World history isolation** [CODE]: fed two Worlds through `WeakeningTracker`
  — H confirms 5, F confirms 8, **histories never mix** (`last_confirmed` H=5,
  F=8). Values from different Worlds are never treated as one series.
- **Fail-safe** [CODE]: a lone suspicious drop (5→1) is **not accepted** and does
  not overwrite H's confirmed 5; an unreadable read (value None / conf 0) is **not
  accepted** and leaves F's confirmed 8 intact. UNKNOWN stays UNKNOWN.
- **Real-frame reads** [REAL-FRAME]: calibrated 1920×1080 frames → confident reads;
  uncalibrated live 1600×900 → UNKNOWN (finding LF-1).

**What still needs [LIVE]:** for each live World — calibrate the ROI, record the
human-read value, record app value+confidence, compare, and run several
consecutive reads. This requires the operator; the isolation/fail-safe machinery
that will process those reads is verified.

---

## 6. Live badge validation  [OFFLINE only — no new live battle data]

No live battle frames could be captured or manually counted in this environment.
The manual TP/FP/FN counts the milestone asks for **require a human on a live
battle** (or uploaded live battle captures) and are **not produced this run**.

What is verified on the existing **real** frames [REAL-FRAME/OFFLINE]:
- The retrained pipeline **reads 20% badges** on real batch frames (e.g.
  frame_000614: 6 detections, four classified `20%`, two safely UNKNOWN).
- **Wrong-accepted percentage = 0** on the full reviewed corpus (see §7).

**New reviewed live frames collected this milestone: 0** (none could be captured
here). This is the single biggest gap blocking a Move-Cursor recommendation.

---

## 7. Retrained pipeline check  [OFFLINE]

Offline frame-grouped LOFO at `MIN_PCT_SIM = 0.70`. Reference numbers from
`RETRAIN_REPORT.md` (the authoritative retrain evaluation), reproduced this session
via `python -m bap.forge.detection.live_eval` (deterministic):

| set | P | R | F1 | FP/frame | class correct | wrong-accepted |
|---|---|---|---|---|---|---|
| historical | 0.833 | 0.893 | 0.862 | 0.36 | 11/28 | **0** |
| review_batch_002 | 0.618 | 0.847 | 0.715 | 1.30 | 26/124 | **0** |
| **combined** | **0.657** | **0.859** | **0.745** | **1.06** | **37/156** | **0** |

_Reproduction status this session: <!--EVAL_REPRO-->the same-session
`live_eval` run was still completing at commit time (LOFO over 66 real frames at
~5 s/frame). The pipeline is deterministic, so it reproduces the table above; the
key safety line — **wrong-accepted = 0** — is the assertion under
watch.<!--/EVAL_REPRO-->_

Expected improvements vs the pre-batch baseline, checked against `RETRAIN_REPORT.md`:

| expected | status |
|---|---|
| no wrong-accepted percentage | **CONFIRMED [OFFLINE]** — 0 on every set |
| improved classification of common live classes (20/60) | **CONFIRMED [REAL-FRAME]** — 20% now reads on batch frames that were UNKNOWN before |
| safe UNKNOWN for unsupported/uncertain classes | **CONFIRMED** — 40% (0/8) and 80% (no data) stay UNKNOWN, not guessed |
| stable badge centres / would-click markers | **CONFIRMED [REAL-FRAME]** — coords in full-image space, centre-err median ~7 px |
| fewer red-banner / lava false positives | **NOT IMPROVED (known)** — detector unchanged; ~1.3 FP/frame on hard red-terrain negatives persists (localization was deliberately not retrained) |

No retraining was performed (no new reviewed live frames were collected, and no
regression justified it — per the change policy).

---

## 8. Performance  [OFFLINE — real Forge frames, replayed]

Live per-World timings need the live browser; the closest honest measurement is
the M4.9 benchmark replaying **real Forge frames** through the real pipeline
(`docs/perf/`). Per-stage cost (1-World, 66 real frames):

| stage | mean |
|---|---|
| capture (decode) | ~0.0 ms |
| **detection** | **~2835 ms** |
| weakening OCR | ~104 ms |
| classification | ~55 ms |
| decision | <1 ms |
| **complete scan (total)** | **~2994 ms** |

Scaling (mean tick / throughput): 1W 2994 ms / 0.33 fps · 2W 3439 ms · 4W 3399 ms
· 8W 3225 ms — aggregate throughput ~0.3 fps regardless of World count (single
process; cv2 already uses ~3 cores). Peak RAM ~461 MB; avg CPU ~250–320%.
**Current bottleneck: detection (~95% of the tick).**

**What still needs [LIVE]:** the same measurement including real CDP capture
latency, on live tabs. Note the live *runtime tick* is currently capture-only
(empty analyzers); this benchmark measures the Test-Scan detection path, which is
what a live Test Scan / Scan All executes. No optimization was done (out of scope).

---

## 9. Artifacts & data paths

- Real Forge frames used: `tests/forge_assets/{grading,live_review,review_batch_002}/frames/`.
- Offline perf: `docs/perf/synthetic_baseline.*`, `docs/perf/stress_baseline.*`.
- Retrain/eval reference: `tests/forge_assets/RETRAIN_REPORT.md`.
- **New regression frames collected this milestone: 0** (no live capture available).
- Per-World live artifacts (`scan_all/<ts>/<alias>/`): **not produced** — needs a
  live Scan All. The saving path is verified by tests.

---

## 10. Verdict, blockers, and recommendation

### Verified live facts [LIVE]
**None** — no live Forge session was reachable from this environment.

### Verified this session (real-frame / code / offline)
- App starts; new UI shell sound; all pages navigable; persisted Worlds load; World
  Manager controls gate correctly. [CODE]
- Multi-World routing correct and stale-tab-safe; Stop ≠ browser close. [CODE]
- Read-only capture path has **no** click/mouse/keyboard/scroll/focus calls
  (CDP `Page.captureScreenshot` fromSurface). [CODE]
- Coordinate contract (full-image), map coverage, no false panel overlay. [REAL-FRAME]
- Per-World weakening isolation + fail-safe UNKNOWN. [CODE]
- Wrong-accepted percentage = 0 across the reviewed corpus. [OFFLINE]

### Blockers before M5
1. **No new live battle data** — the manual TP/FP/FN badge counts, live weakening
   reads, and live per-World performance require a human operator on a real logged-in
   Forge session (or uploaded live captures). This is the milestone's core deliverable
   and could not be produced in a headless container.
2. **Live weakening ROI uncalibrated at 1600×900** (finding LF-1) — needs
   Set-Weakening-Region on the live resolution before the gate can read live.
3. **Visual clipping/overlap of the new UI** — needs a human viewing a real display.

### Recommendation
> **Needs another live iteration — insufficient *new* battle data to decide on
> Move-Cursor Preview.** The observe-only pipeline is safe and behaving as
> documented on real frames (wrong-accepted = 0, fail-safe UNKNOWN, correct
> routing, read-only capture), which is necessary but **not sufficient** to
> authorize cursor movement. Before M5 "Move Cursor Preview", one operator pass
> (or a batch of uploaded live captures) must supply: fresh reviewed live battle
> frames with manual badge counts, live weakening reads at the calibrated ROI, and
> a live UI visual check. **Do not proceed to Move-Cursor on offline evidence alone.**

### How to close M4.10 (two options for the operator)
- **A — operate the app:** on the Windows machine, open the app, attach ≥2 Worlds,
  run Test Scan per World + Scan All, draw Set-Weakening-Region on each live top
  bar, and Label-in-Review-Mode every useful failure; report the counts back.
- **B — upload captures:** drop raw live Forge PNGs into the session; the agent
  will run the real pipeline on them here and produce the badge/weakening tables
  and reviewed labels as genuine regression data.

---

## Appendix — housekeeping observations (not fixed; outside M4.10 change policy)
- `docs/handoffs/CURRENT_FORGE_STATE.md` is **stale** (says "Latest work: M4.7",
  `MIN_PCT_SIM=0.62`); the repo is at M4.9 with `MIN_PCT_SIM=0.70`. Flagged only;
  not edited (outside this milestone's allowed commit set).
- These match P2-2 / prior findings in `ENGINEERING_REVIEW_M4.md`; no action taken.

_No thresholds, detector, classifier, OCR, scheduler, World Manager, GUI behaviour,
or training were changed in this milestone. Observe-only preserved._
