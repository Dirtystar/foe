# Collecting province-panel frames (operator guide)

_How to gather the open-panel screenshots the dataset is missing, using the one gated
click already in the app. This is an **operator** task (it performs a real single click
to open a province) — it is **not** part of Marek's non-technical, never-clicks
screenshot loop. Keep it to yourself or a trusted operator._

## Why

The dataset has **zero** open-panel frames — the GBG map never shows the weakening %,
which lives in a province's detail panel (see `docs/design/GBG_MAP_FACTS.md`). The panel
weakening-reader (the next real step toward clicking) can't be built without real panel
frames. The app now **saves the panel frame on a successful open**, so a short session of
opening provinces produces exactly the frames we need.

Each open — success or not — is saved as a bundle under the app's data dir:

```
<data>/forge/captures/
    panel_<ts>/     screen.png  classification.json  context.json   ← a confirmed panel
    unknown_<ts>/   screen.png  classification.json  context.json   ← anything else (also useful)
```

(`<data>` is the app data dir, e.g. `%LOCALAPPDATA%\...\data` on Windows or
`~/.local/share/...` on Linux.)

## One-time setup

1. Start the dedicated Chrome (`3 - Start Chrome.bat`) and log into your Forge world; open GBG.
2. Launch the app (`4 - Run.bat`), set **Browser mode → External Chrome (CDP)**, attach the world.
3. Open the **Vision Debugger** on the live world.
4. **Calibrate the panel click point** once (Panel Click Point Calibration) so the click
   lands on a province — see the M6A.1 calibration overlay. This is measurement only.

## Collect (per province)

1. In the Vision Debugger, **Enable clicking for this session** (it is off by default).
2. Point at a province you want to open (the would-click target).
3. Click **Open Province & Observe State**. The app performs **one** gated click, waits
   briefly, then honestly reports the resulting UI state:
   - **PROVINCE_PANEL ✅** — the panel opened; the frame is saved to `panel_<ts>/`, and the
     result line shows the saved path.
   - **UNKNOWN / GBG_MAP** — not the panel; the frame is saved to `unknown_<ts>/` for review.
4. Close the panel, move to another province, repeat. A dozen varied provinces
   (different weakening states, own vs enemy) is a good first batch.

There is no loop and no retry — one click, one observation, STOP. You drive each one.

## Export & send

Turn the saved bundles into committable frames:

```
python -m bap.forge.collect              # summary: how many panel / unknown collected
python -m bap.forge.collect --export     # copy them into dataset/panels/ (idempotent)
```

Each frame is copied to `dataset/panels/<state>_<world>_<ts>.png` with a `manifest.csv`
row. Then commit `dataset/` and push (or, on Windows, `6 - Collect Frames.bat` runs the
export for you and `5 - Push.bat` also exports automatically before sending).

The export is **idempotent** — collect a few, export, push, repeat across sessions
without duplicating frames.

## What happens with the frames

Once real `panel_*` frames land in the repo, they unblock the next milestone: a panel
weakening-reader built and evaluated against **real** pixels instead of test fakes. The
`unknown_*` frames are equally valuable — they show exactly where the classifier or the
click is wrong.

## Safety notes

- The clicking feature is **off by default** and must be enabled **per session**.
- It performs a **single** click to open a province — no battle, no repeated clicking, no
  automation. Every click is audited.
- This activity is for an operator who understands it opens provinces. Do **not** fold it
  into the contributor (Marek) loop, which is promised to be screenshot-only.
