# Forge test assets (screenshot fixtures)

Real Forge of Empires screenshots used to build and grade the **badge detector**
(M1a) and the **weakening OCR reader** (M1b). Nothing here is production code —
it's the ground-truth dataset the detector tests assert against.

> **Badge detection is the primary go/no-go gate.** OCR of the top-bar
> "current weakening" number is a separate, non-blocking submilestone.

---

## 1. Exact screenshot requirements

- **PNG, lossless only.** Never JPEG — compression artifacts wreck template
  matching. (See the reminder in §7.)
- **Full browser content area** (the whole game canvas), at native resolution —
  not a cropped region, not a photo of the screen.
- Content is the **Guild Battlegrounds map view** (sectors + weakening badges).
  For OCR fixtures, make sure the **top bar** with the current weakening number
  is visible.
- Capture the game **exactly as the app will run it**: same browser (Chromium),
  same window size, same browser zoom, same Windows display scaling. Keep this
  **constant** across the first dataset (see the reference setup in §8).

**Coverage matrix — aim for ~12–20 images:**

| Kind | How many | Notes |
|---|---|---|
| Each badge % (20/40/60/80/100) present | ≥2 each | the core positives |
| Several **different** badges in one shot | ≥1 | mixed detection |
| Several badges of the **same** % | ≥1 | duplicate handling |
| Badges **close together / overlapping** | ≥1 | non-max-suppression test |
| **No badges at all** | ≥2 | false-positive resistance |
| Top bar with different weakening numbers | ≥3 | OCR (incl. 0 and a high value) |

If you will run more than one zoom/resolution/world, add a small set **per
configuration** and record it in the metadata.

## 2. How to capture them

Recommended (matches how the app captures):

1. Open the world in Chromium at the reference setup (§8).
2. Press **F12 → Ctrl-Shift-P → type "screenshot" → "Capture full size
   screenshot"** (DevTools), **or** use Windows **Snipping Tool** on the browser
   content area. DevTools full-size capture is preferred — it's lossless PNG at
   true pixels.
3. Save as PNG into this folder using the naming convention (§6).
4. Do **not** resize, crop, re-encode, or run it through any "optimizer."

## 3. Required metadata (`labels.json`)

Every image gets an entry in `labels.json` (template provided next to this file).
Per image:

- `file` — the PNG filename in this folder.
- `viewport_w`, `viewport_h` — the browser content pixel size.
- `browser_zoom_pct` — e.g. `100`.
- `windows_scaling_pct` — Windows *Display → Scale*, e.g. `100`.
- `badges` — list of `{ "pct": 20|40|60|80|100, "cx": <int>, "cy": <int> }`.
  Empty list `[]` for a no-badge image.
- `weakening_number` — the integer in the top bar, or `null` if not visible.

`cx`/`cy` are **approximate badge centers in original image pixels** (the tests
allow ±10 px). They are ground truth for the *detection center*, not a click
point.

## 4. How to estimate cx/cy

Use the bundled helper (standalone, stdlib only — needs Python's tkinter, which
ships with the standard Windows installer):

```
python tests\forge_assets\label_helper.py tests\forge_assets\map_01.png
```

- It prints the image **width × height**.
- Click each badge's **center**; a marker is drawn and the **original-pixel**
  `cx, cy` is printed (it corrects for any on-screen downscaling automatically).
- Press **u** to undo the last point, **c** to clear, **s** to print a
  ready-to-paste JSON snippet, **q** to quit (also prints the snippet).
- Paste the points into that image's `badges` entry and fill in each `pct`
  (the helper leaves `pct` as `null` for you to set).

## 5. Examples

**Positive** (`map_01.png` — two badges + top-bar number 8):
```json
{ "file": "map_01.png",
  "viewport_w": 1920, "viewport_h": 1080,
  "browser_zoom_pct": 100, "windows_scaling_pct": 100,
  "badges": [ { "pct": 60, "cx": 812, "cy": 430 },
              { "pct": 20, "cx": 1040, "cy": 512 } ],
  "weakening_number": 8 }
```

**Negative** (`empty_01.png` — no badges; used for false-positive resistance):
```json
{ "file": "empty_01.png",
  "viewport_w": 1920, "viewport_h": 1080,
  "browser_zoom_pct": 100, "windows_scaling_pct": 100,
  "badges": [],
  "weakening_number": 0 }
```

## 6. Naming convention

`<kind>_<NN>.png`, two-digit index, lowercase:

- `map_01.png` … — map views with badges (general positives)
- `overlap_01.png` … — overlapping / very close badges
- `empty_01.png` … — no badges (negatives)
- `topbar_01.png` … — shots focused on the top-bar weakening number (OCR)

If you capture multiple setups, suffix the setup, e.g.
`map_1920x1080_z100_s100_01.png`, and record the same values in `labels.json`.

## 7. PNG must be lossless

Save/keep everything as **PNG**. Do not convert to JPEG/WEBP or run through
image compressors — even "visually identical" lossy re-encoding shifts pixels
enough to hurt template matching.

## 8. Recommended reference setup (first dataset)

Lock these for the first batch so we tune to a known target, then test
robustness afterward:

- **Browser zoom: 100%**
- **Windows display scaling: 100%**
- **Fixed viewport / window size** — pick one and keep it (e.g. maximized on a
  1920×1080 display, giving roughly a 1920×~960 content area — record the actual
  numbers in `labels.json`).

Don't worry about hitting exact pixels; just keep the setup **constant** across
the dataset and write down what it was.

---

When the PNGs and a completed `labels.json` are in this folder, the M1a badge
detector will be built and graded against the agreed accuracy gate (badge recall
≥95%, precision ≥98%, %-classification ≥98%, center ≤10 px, overlapping badges
counted separately, zero false positives on the negatives).
