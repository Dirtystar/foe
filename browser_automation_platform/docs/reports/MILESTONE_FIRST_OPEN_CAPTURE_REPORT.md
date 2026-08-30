# Milestone — Capture the panel frame on a confirmed open (make the first real click productive)

_A small, honest extension of the province-open observation. Until now the app saved a
screenshot **only when the click did not land on `PROVINCE_PANEL`**. But the frame we
most need has never existed: the **success** frame — an actual open province panel. The
dataset has **zero** of them, and the panel weakening-reader (the next step toward
clicking) cannot be built without one. This milestone makes a confirmed open **also**
save its frame, so the first real live click grows the dataset **whatever the outcome**._

## Why this, now

The user asked whether it's time to work on clicking. The clicking *mechanism* already
exists (M6A.1 single gated click + `open_province_and_observe`). What blocks the next
real step — a panel weakening-reader — is **data**: we have never captured an open
panel. The previous observation flow, by explicit earlier design, captured only
not-`PROVINCE_PANEL` states. That means the very first successful live click would
classify the panel, report "confirmed", and then **throw the panel screenshot away** —
discarding the exact frame the dataset lacks.

This milestone closes that gap so the first live run (done locally, where Chrome is
available) is maximally productive: one gated click, and the resulting frame is saved
**on success or on surprise**, ready to pull.

## What changed (additive, no behavior removed)

| Piece | Where | Change |
|---|---|---|
| Capture writer | `bap/forge/state/province_open.py` | Extracted `_save_capture(..., prefix)`; `save_unknown_capture` now a thin wrapper (`unknown_*`, unchanged); new `save_confirmed_capture` writes `panel_*`. |
| Observation | same file | `observe_province_open(..., capture_confirmed=False)`. When `True` **and** observed is the expected `PROVINCE_PANEL`, the success frame is saved to `panel_<ts>/`. Default `False` preserves the prior contract exactly. |
| Controller | `bap/forge/click/open_verify.py` | `open_province_and_observe(..., capture_confirmed=True)` — the live-run entry point keeps the success frame by default. Result reason now names the saved path on success ("Panel frame saved: …") as well as on review captures. |

The `unknown_*` capture path, the classifier, the gate, the single-click spine, and
`open_and_verify` (the %-path) are **untouched**.

## Honesty & scope (unchanged principles)

- **Still one click, one observation, STOP.** No retry, no %-read, no next action.
- **Observed state is still never reinterpreted.** `capture_confirmed` only decides
  whether a *confirmed* frame is *also* saved; it never changes what is reported.
- **Capture stays best-effort.** A write failure returns `None` and never affects the
  flow (`save_confirmed_capture` is covered by a best-effort test).
- **Distinct folders** — `panel_*` (success) vs `unknown_*` (surprise) — so the missing
  success frames are trivial to find and promote into the dataset.

### Deliberate change to an earlier decision (flagged)

An earlier milestone explicitly scoped capture to **non-`PROVINCE_PANEL`** observations.
This milestone intentionally widens that: the success frame is now *the* most valuable
capture, because we have none. The change is **opt-in** (`capture_confirmed`, default
`False` at the observation layer) and only defaulted **on** at the live-run controller
entry point — so nothing captures success frames unless a caller asks. The old contract
remains the default everywhere else.

## Tests (all green)

- **Observation** (`test_province_open.py`, +3): confirmed panel with
  `capture_confirmed=True` → saved to a `panel_*` bundle (screen.png + context with
  `observed_state=PROVINCE_PANEL`); confirmed panel **off by default** → nothing saved
  (prior contract held); `save_confirmed_capture` bad path → best-effort `None`.
- **Controller** (`test_open_province_observe.py`, +assert): the happy path saves a
  `panel_*` frame by default while still performing **exactly one** click.
- Full unit suite: green (see commit).

## Future Simplifications

- `save_unknown_capture` / `save_confirmed_capture` are two three-line wrappers over one
  `_save_capture`. Fine now; if a third capture kind appears, pass the prefix directly
  and drop the wrappers.
- Still **no capture store** — two prefixes and a timestamp dir remain enough. A real
  home (index, dedup, retention) is justified only once a live loop produces captures
  faster than a human reviews them.
- The `capture_confirmed` seam exists so the success frame is opt-in rather than forced
  on every observer; if only the live controller ever wants it, the observation-layer
  flag could later collapse into the controller.

## Recommended next milestone (one, unchanged)

**Run the first real `Open Province & Observe State` on a live world (locally).** It now
produces a saved frame on *every* outcome — a `panel_*` success frame that unblocks the
panel weakening-reader, or an `unknown_*` frame that tells us exactly what's wrong. That
single live click is the smallest real step toward clicking, and it is now maximally
productive. _(Await approval / a local run before building the weakening-reader.)_
