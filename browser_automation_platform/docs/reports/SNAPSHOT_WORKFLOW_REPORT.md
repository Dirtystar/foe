# Snapshot Workflow Report (Milestone 4.13)

The live Forge battleground changes within minutes, so a good scan is gone before
an investigation finishes. This milestone makes **every interesting live scan a
permanent, reproducible artifact** — one click freezes it, one click reviews it,
one click turns it into a regression fixture. Observe-only throughout: snapshots
write files and open the existing Review Mode; nothing clicks, moves the cursor,
or types. No detector/classifier/OCR/scheduler/threshold change.

## 1. Snapshot format

`Save Snapshot` (from the Vision Debugger / Test Scan and from the Vision
Validation page) writes one timestamped, self-contained directory:

```
<data-dir>/snapshots/<YYYY-MM-DD_HH-MM-SS>_<alias>/
    frames/raw.png        # the ONE raw capture — the only analysed pixels
    annotated.png         # the drawn overlay (ROIs, badges, would-click) — never analysed
    scan.json             # the full pipeline trace (scan.to_dict())
    world.json            # the World this came from (alias, hostname, cadence, allowed %)
    calibration.json      # the ROIs actually used, keyed by capture geometry
    labels.json           # ground truth (the ONLY file review may rewrite)
    metadata.json         # provenance (below)
    validation_report.md  # present when saved from Vision Validation
```

`metadata.json` records: World alias, URL, capture resolution, device-pixel-ratio,
viewport, timestamp, **detector version** (e.g. `badge-colorprior+emblem+nms@0.62`),
**classifier version** (e.g. `exemplar-cosine@min_sim=0.70;exemplars=154`), **git
commit**, image MD5, decision, weakening value, and the detector stage counts.

**Why `frames/raw.png` (not a flat `raw.png`):** Review Mode enumerates a *frames
directory* by globbing `*.png`. Keeping the single raw capture in its own
`frames/` subdir means "Open in Review" is a **zero-copy** launch — Review Mode
sees exactly one frame and nothing else (the annotation is not mistaken for a
frame).

**Immutability:** a snapshot is immutable **except for `labels.json`**. Reviewing
updates only labels; `frames/raw.png`, `annotated.png`, and `scan.json` are never
rewritten (proven by a byte-hash test).

## 2. Review workflow

`Open Snapshot in Review` calls `run_review(frames/, labels.json, calibration.json)`
directly on the snapshot — **no copying, no directory hunting**. Review Mode loads
the raw image, the (seeded) labels, and the calibration automatically. The operator
adds missed badges, removes false positives, assigns 20/40/60/80/100, and marks
negatives reviewed. On save, only `labels.json` changes; the snapshot stays a
faithful record of the original scan.

Labels are seeded from the detector's accepted badges as an **unreviewed** starting
point (`reviewed=false`), so they are never treated as ground truth until a human
confirms them — the operator corrects rather than places from scratch.

## 3. Dataset workflow

`Import Snapshot into Dataset` copies the snapshot's `frames/raw.png` into a target
dataset's `frames/` and merges its label into the dataset's `labels.json`
(re-keyed to a stable per-snapshot filename). It **deduplicates by image content
hash (MD5)**: importing the same capture twice is a no-op that reports the existing
frame. The snapshot's `metadata.json` is preserved alongside under
`imported_meta/<name>.json`. Distinct images are both kept.

Because the dataset layout it writes (`frames/` + `labels.json`) is exactly the
one `detection.dataset` loads, an imported snapshot **immediately becomes a
first-class regression fixture** for `live_eval` once the dataset is wired in.

## 4. Regression workflow

Snapshots turn transient live situations into permanent regression assets:

1. Operator hits a bad live case (e.g. a false-positive-heavy negative, or a rare
   40%/80% badge). One click → snapshot.
2. `Open in Review` → correct/confirm → labels frozen.
3. `Import into Dataset` → the frame + reviewed labels join a dataset, deduped.
4. `python -m bap.forge.detection.live_eval` over that dataset measures the case
   forever after — the live game changing can no longer erase the example.

This directly addresses the M4.12 gap where the operator's reviewed H/D frames
were lost because they lived only in a local session and the live board had moved
on: with snapshots, each is a committed, reproducible fixture.

## 5. External Chrome architecture (design only)

Full design in `EXTERNAL_CHROME_ATTACH.md`. Summary: BAP should optionally
**attach to an operator-launched Chrome over CDP** (`connect_over_cdp`) instead of
launching Chromium — the operator owns the browser and profile, BAP is a read-only
guest that discovers tabs and maps Worlds by hostname (reusing today's
reattachment). **Closing BAP disconnects, never closes Chrome.** A separate Chrome
profile is recommended. This fits the existing hexagon as a new browser/tab-source
**adapter** behind the unchanged ports; capture stays the read-only CDP screenshot.
**Not implemented this milestone.**

## 6. What was built

- `forge/snapshots.py` (Qt-free): `write_snapshot`, `load_snapshot`,
  `review_paths`, `import_into_dataset`, plus version/hash helpers.
- `gui/snapshot_actions.py`: shared `Save Snapshot` → offer `Open in Review` /
  `Import into Dataset`.
- Wired into the **Vision Debugger** (Test Scan) and the **Vision Validation** page
  (which also bundles its `validation_report.md`).
- Tests: creation, metadata completeness, reload, review round-trip immutability,
  import dedup + label/metadata preservation, distinct-image retention, and GUI
  button wiring.

Observe-only preserved; safety invariants (fail-safe UNKNOWN, wrong-accepted = 0)
untouched.
