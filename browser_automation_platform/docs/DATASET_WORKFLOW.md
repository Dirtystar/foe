# Dataset / Snapshot / Review — one coherent workflow (Milestone 4.15)

This is the single, unambiguous answer to *"where does reviewed data live, and
what does opening Review edit?"*

> **There is exactly one editable Reviewed Dataset. Every "open Review" action in
> the UI edits that exact dataset. Snapshots are immutable archives. AppData is
> scratch.**

Everything below follows from that one rule. It replaces the earlier state where
three different places were independently editable in Review (an AppData
`forge/live_review` folder, each snapshot's own `labels.json`, and the repo-root
`dataset/`), which is what caused reviews to land somewhere other than where the
operator expected.

## The three roles

| Thing | Role | Mutable? | Where |
| --- | --- | --- | --- |
| **Reviewed Dataset** | The one ground truth every Review edits and the classifier/eval train from | **Yes** — this is the only editable review target | `dataset_store.reviewed_dataset_dir()` |
| **Snapshot** | A permanent, reproducible archive of one scan (raw + annotated + trace + world + calibration + metadata) | No (immutable). Reviewing one **imports** it into the dataset and reviews the copy | `<data>/snapshots/<ts>_<alias>/` |
| **AppData scratch** | Debug artifacts (`Save artifacts…`, `Scan All` per-world outputs) | Throwaway — never a review target | `<data>/forge/...` |

## Where the one dataset lives

`dataset_store.reviewed_dataset_dir()` resolves it in this order:

1. **`BAP_DATASET_DIR`** environment variable — explicit override (used by tests).
2. The repo-root **`dataset/`** when running from source. This is the *same*
   directory the training + evaluation loader discovers
   (`classify.default_snapshot_dataset_dir` delegates here), so what you review is
   exactly what the classifier learns from.
3. **`<app-data>/dataset`** when installed/frozen with no repo checkout.

Layout (created on first use):

```
<reviewed-dataset>/
    frames/            one PNG per reviewed frame
    labels.json        the ONE ground-truth file every Review edits
    calibration.json   weakening / battle-map ROIs, keyed by capture geometry
    imported_meta/     provenance for frames imported from snapshots
```

## The operator workflows — all end in the same dataset

**Label a live/offline scan** (Vision Debugger → *Label in Review Mode…*)
→ the capture is added to the Reviewed Dataset (`dataset_store.add_frame`, deduped
by image hash, detections seeded as an **unreviewed** starting point) and Review
Mode opens **on that dataset**, positioned at the new frame. Confirm and **Save**.

**Review a snapshot** (snapshot → *Import + Review* / *Open Snapshot in Review*)
→ the snapshot's raw frame + label + ROIs are imported into the Reviewed Dataset
(deduped), then Review Mode opens **on the dataset** at the imported frame. The
snapshot itself is never modified.

**Import a snapshot** (snapshot → *Import into Dataset*, or Datasets → *Import
snapshot…*) → imported into the Reviewed Dataset, deduped by hash. No directory
picker: there is only one dataset, so there is nothing to choose.

**Open the dataset directly** (Datasets → *Open Dataset in Review*)
→ Review Mode on the Reviewed Dataset. The Datasets page shows its exact path and
frame / reviewed / labelled counts.

## What Review Mode writes

Review Mode is explicit-save (Milestone 4.14): edits reach disk only when you press
**Save**, which writes atomically to the dataset's `labels.json` and shows the full
path. `reviewed=true` is written only via the explicit **Reviewed** control (it also
works for zero-badge negatives) — never inferred. Only reviewed, classified badges
become classifier exemplars, so an imported-but-not-yet-reviewed frame changes no
behaviour until a human confirms it.

## Invariants (unchanged by this milestone)

Observe-only throughout — nothing here clicks, moves the cursor, or types. This
milestone changed **only** the dataset/snapshot/review *plumbing*: the detector,
percentage classifier, similarity/threshold values (`MIN_PCT_SIM = 0.70`, detector
`0.62`), OCR, weakening gate, runtime, and scheduler are untouched.
