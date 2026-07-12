# Weakening-reader spike (against the user-corrected calibration)

Both readers evaluated on the 15 reviewed weakening values, using the corrected
per-resolution region in `calibration.json` (`1920x1080 → x678 y477 w56 h25`).

> **The 15 grading frames are independent snapshots from different Worlds and
> unrelated moments — NOT a time series.** They are used only for *per-frame* OCR
> accuracy. No monotonicity, downward-jump, or temporal check is applied across
> this dataset, and the sequence of values (86, 92, 111, 5, …) carries no
> temporal meaning. Temporal plausibility exists only at **runtime**, tracked
> **independently per World** (`WeakeningTracker`, keyed by world id / alias) —
> values from different Worlds are never compared.

Reproduce: `python -m bap.forge.detection.weakening_eval tests/forge_assets/grading/frames`

## Results

| Reader | Exact @ calibrated region |
|---|---|
| OCR (numeric whitelist) | **40%** (6/15) |
| Deterministic digit templates | **7%** (1/15) |
| OCR, region aligned per frame | **87%** (13/15) |

## Are the errors OCR, or region/layout drift?

**Overwhelmingly region/layout drift.** Of the 9 calibrated-region failures:

- **7 are region/layout drift** — the grading set is drawn from several capture
  sessions whose top bars sit at slightly different x-positions, so one fixed
  rectangle cannot align to all of them. A small shift (typically −18 px x) reads
  each of these correctly:
  `frame_000183 (111), 000460 (8), 000466 (8), 000486 (12), 000596 (1), 000650 (0), 000654 (0)`.
- **2 are genuine OCR errors** — no shift helps:
  `frame_000021 (86 → 36)` and `frame_000070 (92 → 36)` — high-value two-digit
  numbers where Tesseract misreads the leading digit.

So **given a correctly-aligned region, OCR reads 13/15 (87%)**; only 2 are true
OCR limitations. In production the user runs one consistent capture setup, so a
single calibration aligns to *every* frame and the drift failures disappear —
the expected field accuracy is ~87%, bounded by the two genuine misreads.

**Template matching (7%) is not competitive** and is far more sensitive to the
region than OCR; OCR is the reader to use.

## Confidence

Tesseract's confidence on these tiny digits is low even when the read is correct
(mean ~0.18, sometimes 0 for single glyphs). So a strict confidence threshold is
**over-conservative but safe**: it errs toward UNKNOWN → no action, never toward
acting on a bad read.

At runtime the stronger gate signal is **per-World consensus + temporal
plausibility** (`WeakeningTracker`): a value is confirmed only when consecutive
confident reads *for that World* agree, and a large unexplained drop (the exact
86 → 36 / 92 → 36 misreads above) is treated as suspicious and does **not** become
the confirmed value — it stays UNKNOWN. This runs per `world_id`; there is no
global history across tabs. The two genuine per-frame OCR errors therefore remain
documented reading errors, but at runtime they would be rejected by consensus
rather than acted on.

## Fail-safe (unchanged)

- unreadable / low confidence → **UNKNOWN → no action**
- value ≥ world limit → **STOP**
- only a confident value below the limit → **CONTINUE**

Never continues blindly.
