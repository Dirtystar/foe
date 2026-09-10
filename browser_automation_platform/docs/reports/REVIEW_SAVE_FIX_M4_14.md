# Reliable Review Save Workflow — Fix Report (Milestone 4.14)

_Observe-only. No detector, classifier, thresholds, OCR, weakening, runtime,
scheduler, World Manager, snapshot format, or dataset semantics changed — this
milestone only makes Review-Mode persistence **explicit, reliable, and visible**._

## 1. Root cause (reproduced before any code change)

Using the exact workflow
`python -m bap.gui.forge_review dataset/frames --labels dataset/labels.json`,
I reproduced the persistence behaviour headlessly against a copy of the committed
`dataset/`:

- **Which labels path is opened / written:** `main()` passes `--labels
  dataset/labels.json` → `run_review(...)` → `LabelSession.open(frames_dir,
  labels_path)` → `LabelStore.load("dataset/labels.json")`, correctly **bound to
  that exact path**. Badge and percentage edits autosaved there (verified: after
  assigning 20%, the on-disk file showed `pcts [20,20,20]`). **No duplicate
  labels.json** was created under `frames/` on this path.
- **The real bug — `reviewed=true` was never written by any explicit control.**
  The only code that set it was an **implicit** branch in `_nav` (frame
  navigation): `if cur.badges and all(b.pct is not None …): cur.reviewed = True`.
  Consequences:
  - **Zero-badge negative frames could NEVER be marked reviewed** (`cur.badges` is
    empty → the guard is always false). This is exactly the committed
    `2026-08-04_..._H` case: `reviewed:false` with `pct:null`.
  - It never fired if the operator **closed without navigating**, or left **any
    badge unclassified**.
  - There was **no visible "Mark Reviewed" control**, no dirty indicator, no save
    confirmation, no `closeEvent`, and **no display of the active labels path** —
    so the operator could not see what was written or where. (A GUI "Label in
    Review Mode" launch writes to the live-review data dir, not
    `dataset/labels.json`, which also looks like "changes gone".)

**Summary:** edits *did* reach the opened file, but `reviewed` could only be set
by an undiscoverable side-effect of navigation that is impossible for negatives —
so `dataset/labels.json` stayed `reviewed:false`, and with no visibility the whole
save felt unreliable.

## 2–6. The fix (explicit, reliable, visible)

Review Mode is now **explicit-save**:

- **Autosave opt-out.** `LabelStore` gains an `autosave` flag (default `True`, so
  the grading labeler and everything else are unchanged). Review Mode sets it
  **off**, so edits live in memory and reach disk **only on an explicit Save** —
  which is what makes "Discard" meaningful.
- **Save button** — writes immediately and **atomically** (`tmp` + `replace`) to
  the exact labels path passed on launch, and shows a visible confirmation:
  `✅ Saved to: <full path> · <time>`. It never writes to a different directory.
- **Dirty state** — any edit (add / move / delete a badge, change a percentage,
  set weakening, toggle reviewed) flips the status to `● Unsaved changes`; a
  successful Save flips it to the timestamped `Saved to:` line.
- **Close safety** — closing with unsaved changes prompts **Save / Discard /
  Cancel** (`closeEvent`): Save writes then closes, Discard closes without
  writing, Cancel keeps the window open. No edit is lost silently.
- **Explicit Reviewed control** — a **Reviewed** checkbox shows the current
  frame's state, works for **zero-badge negatives**, preserves existing badge
  labels, and is written on Save. `reviewed=true` is never inferred from merely
  opening a frame (the implicit nav-review was removed).
- **Path visibility** — the active labels file path is shown
  (`Labels file: <abs path>`), and a **duplicate warning** appears if a *different*
  `labels.json` exists inside the frames folder.

## 7. Files changed

| file | change |
|---|---|
| `src/bap/forge/labeling/model.py` | `LabelStore(autosave=True)` flag + `bind()`; `save()` still always writes when called |
| `src/bap/forge/labeling/session.py` | `_save()` respects the store's `autosave` flag |
| `src/bap/gui/forge_review.py` | Save button, Reviewed checkbox, dirty tracking, `closeEvent` Save/Discard/Cancel, labels-path + duplicate-warning display; removed implicit nav auto-review |
| `tests/unit/gui/test_review_save.py` | new: full save-workflow matrix (§7) |
| `tests/unit/gui/test_forge_review.py` | two autosave tests updated to explicit Save |

## 8. Operator verification (Windows)

Open the committed live snapshot in Review Mode:

```
python -m bap.gui.forge_review dataset\frames --labels dataset\labels.json
```

Expected UI flow:

```
Edit (add/adjust badges, press 1-5 for 20/40/60/80/100)
  → status shows "● Unsaved changes"
  → tick "Reviewed"  (works even with zero badges)
  → click "Save"
  → status shows "✅ Saved to: C:\Users\you\foe\browser_automation_platform\dataset\labels.json · HH:MM:SS"
  → close the window
  → reopen the same command
  → badges, percentages and Reviewed are restored
```

Verify on disk (PowerShell / Git Bash):

```
grep "\"reviewed\": true" dataset/labels.json
# or, Windows CMD:
findstr /C:"\"reviewed\": true" dataset\labels.json
```

You should now see `"reviewed": true`, and the badge percentages you assigned.
The `Labels file:` line in the UI shows the exact path being written; if a stray
`labels.json` sits inside `dataset\frames\`, a red warning tells you edits go to
the file named on that line, not the stray one.

## Test results

See `tests/unit/gui/test_review_save.py` (save writes to the requested path;
persists additions, deletions, percentages, `reviewed=true`; reviewed negative
with zero badges; reopen restores; close prompts; Discard does not write; Cancel
keeps the window open; no duplicate `labels.json` under `frames/`) and the updated
`test_forge_review.py`. Full unit suite run once for the milestone.

_Observe-only preserved throughout; nothing outside the labelling/persistence and
Review-Mode UI was touched._
