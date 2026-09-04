# Forge weakening-badge grading set

The small, human-confirmed ground-truth set the badge detector (Milestone 3) will
be graded against. **15 representative frames** spanning different worlds and
screen states (map + province panel, battle log, army-management dialog, and a
few badge-free negatives), selected from the 236-frame dataset.

## What's here

- `frames/` — the 15 lossless PNG frames (native 1920×1080; never re-encode).
- `labels.json` — per-frame badge centres and percentages, plus a `reviewed`
  flag. It is **pre-seeded** with the auto-suggester's candidate centres
  (`pct: null`, `reviewed: false`) so you mostly *confirm* rather than hunt.

A frame counts as ground truth only once `reviewed` is `true`. Pre-seeded
suggestions are a starting point, not truth — some are wrong (e.g. the army
dialog's red unit icons) and must be corrected.

## How to review (build the truth)

Run the assisted labelling tool over this folder:

```
python -m bap.forge.labeling tests/forge_assets/grading/frames
# (labels.json in that folder is loaded and autosaved; resumes where you left off)
```

For each frame:

- Confirm each real weakening badge: click its centre (or keep a suggested dot),
  then press **1–5** for **20 / 40 / 60 / 80 / 100 %**.
- **Right-click** a wrong suggestion (e.g. the panel's combat-type shield, or an
  army-dialog unit) to delete it.
- Press **N** on a frame with no weakening badges to mark it a reviewed negative.
- **←/→** move between frames; everything autosaves.

The detector is then graded against the reviewed frames (recall / precision /
percentage-classification / centre error), so the numbers reflect
human-confirmed truth, not the suggester.

> Scope: this is the grading set only. No detector, OCR, clicking, or battle
> logic is built yet.
