#!/usr/bin/env python3
"""Standalone badge-labeling helper for building labels.json.

NOT production code and NOT a test — a throwaway dev tool. Uses only the Python
standard library (tkinter, which ships with the standard Windows/macOS Python
installers), so it needs no pip installs.

Usage:
    python tests/forge_assets/label_helper.py path/to/map_01.png

It prints the image width x height, shows the image (downscaled to fit the
screen if large), and lets you click each badge's center. For every click it
prints the ORIGINAL-pixel coordinates (it corrects for any on-screen
downscaling). Keys: u=undo last, c=clear, s=print JSON snippet, q=quit.

Paste the printed points into that image's `badges` list in labels.json and set
each `pct` (the snippet leaves pct as null for you to fill).
"""

from __future__ import annotations

import json
import math
import os
import sys

_MAX_W = 1280  # fit the displayed image within this box; clicks are scaled back
_MAX_H = 800


def _fail(msg: str, code: int = 2) -> None:
    print(msg)
    raise SystemExit(code)


def main(argv: list[str]) -> None:
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        _fail(
            "usage: python label_helper.py <image.png>\n"
            "  click each badge center; keys: u=undo c=clear s=snippet q=quit",
            code=0 if argv[:1] in (["-h"], ["--help"]) else 2,
        )
    path = argv[0]
    if not os.path.isfile(path):
        _fail(f"no such file: {path}")

    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - environment dependent
        _fail(
            "tkinter is not available in this Python. On Windows use the "
            "python.org installer (it includes tkinter).\n"
            f"details: {exc}"
        )

    root = tk.Tk()
    root.title(os.path.basename(path))
    try:
        image = tk.PhotoImage(file=path)
    except Exception as exc:
        _fail(f"could not load '{path}' as PNG via tkinter: {exc}")

    w, h = image.width(), image.height()
    # Integer downscale factor so the whole image fits on screen. Clicks in
    # displayed space are multiplied by `factor` to recover original pixels.
    factor = max(1, math.ceil(max(w / _MAX_W, h / _MAX_H)))
    shown = image.subsample(factor, factor) if factor > 1 else image

    print(f"image: {os.path.basename(path)}  size: {w} x {h} px"
          + (f"  (shown at 1/{factor})" if factor > 1 else ""))
    print("click badge centers; keys: u=undo  c=clear  s=snippet  q=quit\n")

    canvas = tk.Canvas(root, width=shown.width(), height=shown.height(), highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=shown)

    points: list[tuple[int, int]] = []
    markers: list[int] = []

    def redraw_status() -> None:
        root.title(f"{os.path.basename(path)} — {len(points)} point(s)")

    def on_click(event) -> None:
        cx, cy = int(event.x * factor), int(event.y * factor)
        cx, cy = max(0, min(cx, w - 1)), max(0, min(cy, h - 1))
        points.append((cx, cy))
        r = 6
        m1 = canvas.create_oval(event.x - r, event.y - r, event.x + r, event.y + r,
                                outline="red", width=2)
        m2 = canvas.create_text(event.x, event.y - 12, text=str(len(points)),
                                fill="red", font=("Segoe UI", 10, "bold"))
        markers.append(m1)
        markers.append(m2)
        print(f"  point {len(points)}: cx={cx} cy={cy}")
        redraw_status()

    def undo(_event=None) -> None:
        if points:
            points.pop()
            for _ in range(2):
                if markers:
                    canvas.delete(markers.pop())
            print("  (undo)")
            redraw_status()

    def clear(_event=None) -> None:
        points.clear()
        while markers:
            canvas.delete(markers.pop())
        print("  (clear)")
        redraw_status()

    def snippet(_event=None) -> None:
        badges = [{"pct": None, "cx": cx, "cy": cy} for cx, cy in points]
        print("\n--- paste into this image's \"badges\" (fill each pct) ---")
        print(json.dumps(badges, indent=2))
        print("----------------------------------------------------------\n")

    def quit_(_event=None) -> None:
        snippet()
        root.destroy()

    canvas.bind("<Button-1>", on_click)
    root.bind("u", undo)
    root.bind("c", clear)
    root.bind("s", snippet)
    root.bind("q", quit_)
    root.protocol("WM_DELETE_WINDOW", quit_)
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1:])
