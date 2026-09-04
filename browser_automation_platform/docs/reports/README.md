# Engineering reports (historical archive)

Milestone reports and research write-ups, kept for provenance. These are
**point-in-time records** — the living status lives in
[`../handoffs/CURRENT_FORGE_STATE.md`](../handoffs/CURRENT_FORGE_STATE.md), and the
current operator guides live in [`../`](../). Reports are not maintained after
their milestone.

| Report | Milestone / topic |
|---|---|
| `ENGINEERING_REVIEW_M4.md` | M4 decision-slice engineering review |
| `LIVE_WINDOWS_REVIEW_M4.md`, `LIVE_WINDOWS_REVIEW_M4_12.md` | Live Windows H/F diagnosis (M4, M4.12) |
| `VISION_VALIDATION_REPORT.md`, `_D2.md`, `_H2.md` | Vision validation passes (M4.11–4.12) |
| `SNAPSHOT_WORKFLOW_REPORT.md`, `DATASET_SNAPSHOT_SOURCE_REPORT_M4_13.md` | Snapshot/dataset workflow (M4.13) |
| `REVIEW_SAVE_FIX_M4_14.md` | Explicit Review save (M4.14) |
| `EXTERNAL_CHROME_ATTACH.md`, `EXTERNAL_CHROME_IMPLEMENTATION_REPORT.md` | External Chrome attach (M4.16) |
| `M5A_CURSOR_PREVIEW_REPORT.md`, `M5A1_WINDOWS_GEOMETRY_REPORT.md` | Move Cursor Preview + Windows geometry (M5A, M5A.1) |
| `LIVE_DATASET_RETRAIN_REPORT.md`, `LIVE_CLASSIFIER_HARDENING_REPORT.md` | Live retrain + classifier hardening (M5A/M5B) |
| `CLASSIFIER_V2_BENCHMARK_REPORT.md` + `classifier_v2/` | Classifier-v2 benchmark + evidence bundle (M5C) |
| `CAPTURE_ALL_CONCURRENCY_REPORT.md` | Capture All async P0 fix |

Evidence bundles referenced by the reports sit alongside them:
`classifier_v2/` (regenerate with `python -m bap.forge.research`; a fresh copy is
written to the repo root and git-ignored) and `live_classifier_hardening/`.
