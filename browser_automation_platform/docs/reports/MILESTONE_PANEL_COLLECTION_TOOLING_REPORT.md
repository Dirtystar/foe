# Milestone — Tooling to collect the panel frames the app needs to learn

_The app now saves a panel frame on a successful open (previous milestone). This
milestone makes that **collectable**: the Vision Debugger writes every open to one
capture folder, and a small CLI turns those captures into committable dataset frames.
One operator session of opening provinces now produces the panel screenshots the dataset
has never had — with a one-command export and an auto-export on push._

## What was added

| Piece | Where | What |
|---|---|---|
| Collect CLI | `bap/forge/collect.py` (new) | `python -m bap.forge.collect` summarises captured bundles (panel / unknown, worlds seen); `--export` copies each frame to `dataset/panels/<state>_<world>_<ts>.png` + a `manifest.csv` row. **Idempotent** — already-exported frames are skipped. Read-only over the game; never deletes captures. |
| GUI capture dir | `bap/gui/forge_debugger.py` | "Open Province & Observe State" now saves into `<data>/forge/captures/` (neutral parent holding both `panel_*` and `unknown_*`), and the confirmed result line shows the saved panel path. |
| Operator guide | `docs/handoffs/COLLECTING_PANEL_FRAMES.md` (new) | How to collect: enable clicking (per session), calibrate the panel point, click Open Province & Observe per province, then export + push. |
| Contributor launcher | `Marek/6 - Collect Frames.bat` (new) | Safe inspect/export helper. Shows the collected count and copies frames into the dataset. |
| Push auto-export | `Marek/5 - Push.bat` | Runs `collect --export` (best-effort) before staging `dataset/`, so frames are sent even if the collect step is skipped. No-op when nothing was collected. |

## How collection works now

```
Vision Debugger → Open Province & Observe State   (one gated click, per province)
    └── <data>/forge/captures/
            panel_<ts>/     screen.png + classification.json + context.json   (success)
            unknown_<ts>/   screen.png + classification.json + context.json   (anything else)

python -m bap.forge.collect --export
    └── dataset/panels/  province_panel_H_<ts>.png ...  + manifest.csv   →  commit + push
```

Collect a few, export, push, repeat across sessions without duplicating frames.

## Boundaries kept

- **Not folded into the non-technical (Marek) loop.** Generating panel frames requires the
  one gated click; Marek's onboarding is promised screenshot-only. The clicking
  instructions live in the operator guide; the `6 - Collect Frames.bat` in Marek's folder
  is **export-only** (read-only, safe) and documented as optional, since `5 - Push.bat`
  already includes any saved frames.
- **No new automation.** The collector still drives each open by hand — one click, one
  observation, STOP. `collect.py` only reads/copies files; it never touches the game.
- **Capture stays best-effort**; the CLI is defensive (a malformed bundle is reported, not
  fatal; a missing `screen.png` is skipped).

## Tests (8 new, all green)

`tests/unit/forge/test_collect.py`: scan classifies `panel_`/`unknown_`; empty dir → no
crash; a bundle missing `screen.png` is flagged and skipped on export; export writes
descriptively-named PNGs + a manifest and is **idempotent** (second run copies nothing,
no duplicate manifest rows); `main` prints a helpful message with no captures and reports
the exported count. Full unit suite: green.

## Next

Everything is in place for the first real collection run (local, operator): open a dozen
varied provinces, `--export`, push. Those `panel_*` frames unblock the panel
weakening-reader — the next step toward clicking — built and evaluated against real pixels
instead of fakes. `unknown_*` frames show exactly where the classifier or click is wrong.
