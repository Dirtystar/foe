# Live Data Collection — Operator Guide (Milestone 5D)

A fast, traceable workflow for gathering live Chrome badge examples across your 8
Worlds. Everything is **observe-only**: it takes read-only screenshots and files
them into the canonical dataset. It never clicks, moves the cursor, types, retrains
a model, or changes any threshold. The percentage classifier only *suggests* labels
— **your label is ground truth.**

## Why we're collecting

The classifier-v2 benchmark (Milestone 5C) showed the limit is **data, not the
algorithm**. Priorities, in order:

1. **80%** — currently **zero** examples. Cannot be classified at all until we have
   real ones.
2. **40%** and **100%** — scarce (single digits).
3. **Live-Chrome examples** of every class (the app sees live captures, but almost
   all exemplars are historical-scale).
4. **Negative (no-badge) maps** — valuable for detector evaluation.

## The workflow for tomorrow

1. **Start External Chrome** (your normal Forge browser).
2. **Attach your 8 Worlds** in the app (World Manager → Scan & Reattach). Set the
   browser mode to *External Chromium*.
3. **Open Live Data Collection** — `Tools → Live Data Collection…`.
4. **Start a session.** Click **Start Session** (records id, time, browser mode,
   Worlds, git commit, dataset path; it survives an app restart). Optionally set a
   per-class target (default 20 each + 20 negatives).
5. **Capture All Worlds.** Click **Capture All Worlds** (or tick specific Worlds and
   **Capture Selected**). Each capture:
   - takes one read-only screenshot,
   - runs the existing detector/classifier for suggestions,
   - saves a snapshot into the canonical dataset with full provenance
     (World, URL, resolution, viewport, DPR/zoom, timestamp, session),
   - **skips duplicates automatically** (by image hash),
   - seeds detected badge positions as **unreviewed** suggestions.
   Move around the battle map between captures to get fresh badges.
6. **Review useful frames.** Select a row → **Open in Review**. Use the queue's
   **Sort → Highest uncertainty** or **Rarest class**, and the **Filter** (Has
   UNKNOWN, 80%, a specific World…) to find the frames worth your time.

   Fast keyboard review (≈5–10 s per simple frame):
   | key | action |
   |---|---|
   | `1 2 3 4 5` | set the selected badge to 20 / 40 / 60 / 80 / 100 % |
   | `Delete` / `Backspace` | remove the selected false detection |
   | `N` | mark a **Reviewed Negative** (no-badge) frame |
   | `R` | toggle **Reviewed** |
   | `Ctrl+S` | Save |
   | `Enter` | **Save and Next** |
   | `← / →` | previous / next frame |
   | `Esc` | cancel the current edit (never discards saved work) |

   The window always shows the frame position (e.g. `12 / 47`), the selected badge,
   the reviewed state, the unsaved-changes state, the labels-file path, and a Save
   confirmation. The explicit **Save** button is always there. **Nothing is marked
   reviewed implicitly** — only you do it.
7. **Mark negatives.** A clean map with no badges? Press `N` → it becomes a reviewed
   zero-badge frame (counts for detector evaluation, excluded from percentage
   exemplars).
8. **Repeat during the day.** Capture bursts across Worlds; the queue and the
   Datasets statistics update live, and the shortage hint tells you the *most useful
   next capture* (a goal, not a promise the class will appear).
9. **Validate Dataset.** Click **Validate Dataset**. It reports (never repairs)
   missing images, orphan labels, reviewed badges with no percentage, duplicate
   images, duplicate badge centres, invalid percentages, calibration mismatches, and
   missing provenance — each with an explicit suggested fix.
10. **Prepare Dataset Commit.** Click **Prepare Dataset Commit**. It shows the files
    added/modified, frames reviewed, the per-class delta vs the last commit, the
    validation status, and the **exact Git Bash commands** — it does **not** run git.
11. **Commit and push** yourself in Git Bash:
    ```bash
    git add dataset/
    git commit -m "Add live collection <session-id>"
    git pull --rebase origin <branch>
    git push origin <branch>
    ```
    Unreviewed frames may be included as *pending* data — the plan warns you, but it
    is allowed.

## Session report

At any point, **Write Session Report** produces
`LIVE_COLLECTION_SESSION_<id>.md` — Worlds, captures, duplicates skipped,
reviewed/pending/negative counts, per-class badges, resolution/source distribution,
dataset validation, and the recommended next data gaps.

## Tips for high-value collection

- Prioritise **80%** badges wherever they appear — they unblock a whole class.
- Grab the **same World at different zoom / window sizes** to broaden scale coverage
  (912/900/1080-tall captures all help).
- A few **negatives per World** are quick wins (press `N`).
- Use **Sort → Rarest class** after labelling to keep surfacing the scarce classes.
- Don't force a label you're unsure of — **UNKNOWN is always safe**; leave it pending.

## What this mode will NOT do

No clicking, no cursor movement, no battle automation, no scheduler, no retraining,
and no change to detector thresholds, `MIN_PCT_SIM`, OCR, weakening, or geometry. It
is a data-gathering surface only.

## Recommended targets for tomorrow

| class | target (new badges) | why |
|---|---|---|
| 80% | **20+** | zero today — top priority |
| 40% | 20 | scarce |
| 100% | 20 | scarce |
| 60% | 20 | broaden live-scale coverage |
| 20% | 20 | live-scale coverage (already common historically) |
| negative frames | 20 | detector evaluation |

Finish with whatever appears naturally across the Worlds — the targets are goals,
not quotas, and the app never fabricates a class that didn't appear.
