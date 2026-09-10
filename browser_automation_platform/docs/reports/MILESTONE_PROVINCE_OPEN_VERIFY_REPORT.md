# Milestone — Verify a province-open produced the expected UI state

_A new product capability, honest and read-only. After the single click that opens a
province (M6A.1), the application now **observes the resulting UI state** and reports
exactly what it saw — expected `PROVINCE_PANEL`, observed `PROVINCE_PANEL` /
`UNKNOWN` / `GBG_MAP` / … — with confidence and the classifier's signals. When it is
not `PROVINCE_PANEL`, it saves the screenshot + classifier output + context for later
review. No %-read, no retry, no next action, no transition logic._

## Summary — what was implemented

| Piece | Where | What |
|---|---|---|
| The observation | `bap/forge/state/province_open.py` (new) | `observe_province_open(after_image)` → `ProvinceOpenObservation` (expected/observed/confidence/signals/captured_path). Reuses Milestone-A `classify_screen`. |
| Save-on-unknown | same file | `save_unknown_capture()` — a **plain helper function** (no store abstraction) that writes `screen.png` + `classification.json` + `context.json`. |
| The runnable flow | `OpenAndVerifyController.open_province_and_observe()` (added; `open_and_verify` untouched) | Reuses the M6A.1 gate → arm → single click → bounded settle-capture, then observes. Audits `PROVINCE_OPEN_OBSERVED`. |
| Read-out | Vision Debugger | "Open Province & Observe State" button → the three honest lines + capture path. |

## New capability

The application can now say, truthfully:

> "I attempted to open a province. I expected `PROVINCE_PANEL`. I observed
> `PROVINCE_PANEL`."  — or "…I observed `UNKNOWN`" (and saved everything for review).

That is the first **verified state transition** end of the vertical slice
(`GBG_MAP → click → settle → observe`). It performs one click and one observation,
then stops.

## Honesty & product-driven data (by design)

- **Observed state is never reinterpreted.** If the click leaves us on `GBG_MAP`, or
  the classifier is unsure (`UNKNOWN`), that is exactly what is reported — no guessing,
  no retry, no inferred intent. `confirmed` is true only when observed *is* the
  expected `PROVINCE_PANEL`.
- **Every not-as-expected observation is captured, not discarded.** The screenshot +
  full classifier output (candidate scores + signals) + execution context land in
  `<data>/forge/unknown_captures/unknown_<ts>/`. That is the product→dataset feedback
  loop: the product creates the candidates; a human later decides whether to add them.
  Capture is best-effort — a write failure returns `None` and never affects the flow.

## Tests (14 new, all green)

- **Observation** (`test_province_open.py`, 7): observed `PROVINCE_PANEL` → confirmed,
  nothing saved; `UNKNOWN` → reported + a bundle with screenshot/classification/context;
  still-`GBG_MAP` → reported honestly (not collapsed to UNKNOWN) + captured; `None`
  image → UNKNOWN + captured (no `screen.png`); no capture dir → nothing written, no
  crash; bad path → best-effort `None`; result is observable via `to_dict`.
- **Controller flow** (`test_open_province_observe.py`, 7): not-confirmed / disabled /
  gate-fail / cursor-moved all block **before** any click (0 clicks); the happy path
  performs **exactly one** click then observes `PROVINCE_PANEL` (`confirmed`), emits
  `PROVINCE_OPEN_OBSERVED`; `UNKNOWN` and still-`GBG_MAP` are reported honestly with
  **one** click and **no retry**.
- **GUI**: the "Open Province & Observe State" button is disabled until clicking is
  enabled for the session.
- The full M6A.1 click suite stays green — `open_and_verify` was not modified.

Full unit suite: green (see the commit).

**Untested by design:** the *positive* `PROVINCE_PANEL` path on **real** pixels — we
still have zero panel screenshots. The controller/observation logic is proven with
injected classifications; the first real confirmation happens live, and any real
`UNKNOWN` there is captured — which is the point.

## Future Simplifications (as requested)

**Which parts feel temporary?**
- `save_unknown_capture()` writing a three-file folder per capture is the deliberately
  boring version. If capture volume grows or we need querying, it will want a real
  home (an index, dedup, retention) — but not yet.
- The `detectors=` / `detect_context=` passthrough on `open_province_and_observe`
  exists mostly so tests can inject classifications; it's a small seam, harmless, but
  it's plumbing, not product.
- `ProvinceOpenResult` vs `OpenVerifyResult` are two sibling result types on one
  controller. Fine for two flows; a third would argue for a shared shape.

**Which abstractions did I intentionally avoid today?**
- **No `UnknownCaptureStore`** (you vetoed it, correctly). Two file-writes and a
  timestamp dir solve today's problem with less code and zero speculation about future
  collection needs.
- **No generic "observation framework."** `observe_province_open` answers *this*
  question well; "what did we expect / what happened / how confident / can we explain
  it" is a *pattern every future capability should follow by hand*, not a base class to
  inherit.
- **No transition/state-machine engine.** The method observes and stops; it does not
  decide the next action.
- **No shared "gate → click" extraction** between `open_and_verify` and
  `open_province_and_observe`. I duplicated the short spine rather than refactor a
  tested safety path — the duplication is cheaper and safer than the wrong abstraction.

**When would each become justified?**
- A capture *store* when a second consumer needs to read/query captures, or a live loop
  starts producing them faster than a human reviews — i.e. once collection is a real
  workflow, not a side effect.
- An *observation* base/protocol once ≥ 3 capabilities each independently report
  expected/observed/confidence/signals and we see real duplication (not imagined).
- A *state machine* the moment we intentionally chain transitions (open → attack →
  battle) — that is a deliberate future milestone with its own safety review, not
  something to pre-build.
- A shared click-spine extraction once a **third** flow needs it, so the common shape
  is evidence-based rather than guessed.

_Principle held: prefer less code; let repetition — not anticipation — justify
abstraction._

## Recommended next milestone (one)

**Prove the `GBG_MAP → PROVINCE_PANEL` transition on real pixels — live, product-driven.**

Everything is now in place to make the first *real* verified transition: run "Open
Province & Observe State" on a live world. Two outcomes, both valuable: it observes
`PROVINCE_PANEL` (the transition is proven and the panel-percentage reader from M6A.1
becomes exercisable), or it observes `UNKNOWN`/`GBG_MAP` and **captures the frames** —
which are exactly the panel screenshots the dataset is missing. Either way the product
advances or the dataset grows, with no dedicated collection milestone. The only code
this needs is whatever the live run tells us is wrong (per the dataset policy).

_(Await approval before starting the next milestone.)_
