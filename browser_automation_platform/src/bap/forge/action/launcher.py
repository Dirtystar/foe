"""Launch the owned farming browser — the production foundation.

Instead of attaching to whatever Chrome the user happens to have open (arbitrary window
size, throttled background tabs, no debug port), the app **owns** the browser: it starts it at
a **fixed window size** (so canvas coordinates like the GBG city entrance are deterministic —
one calibration we ship, not a per-user chore), with **anti-throttle flags** (background tabs
keep loading), a **persistent profile** (login + FoE Helper stay), and the **CDP debug port**
the farm connects to.

    python -m bap.forge.action.launcher              # first run: log in + open GBG on each world
    python -m bap.forge.action.open_targets --worlds worlds_farm.json   # then farm

This is what the shipped .exe will do automatically (bundling its own Chromium). ``no-cover`` —
it only spawns a browser process.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404
import sys

# Fixed window that reproduces a ~1536x695 viewport (entrance calibrated for it). The farm reads
# the live viewport for the Útok/Auto-battle buttons, so only the city entrance is size-tied.
DEFAULT_WINDOW = (1536, 805)
DEFAULT_PROFILE = "foe-profile"
DEFAULT_PORT = 9222

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def _find_chrome():  # pragma: no cover - environment
    for p in _CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return "chrome"


def run_launch(profile=DEFAULT_PROFILE, window=DEFAULT_WINDOW, port=DEFAULT_PORT,
               chrome=None):  # pragma: no cover - live
    exe = chrome or _find_chrome()
    prof = os.path.abspath(profile)
    os.makedirs(prof, exist_ok=True)
    w, h = window
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={prof}",
        f"--window-size={w},{h}",
        "--window-position=0,0",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    print(f"[launch] {exe}\n[launch] profile: {prof}\n[launch] window {w}x{h}, CDP :{port}",
          flush=True)
    try:
        subprocess.Popen(args)  # noqa: S603
    except Exception as exc:  # noqa: BLE001
        print(f"[launch] failed to start browser: {exc}\n"
              "Pass --chrome PATH to your chrome.exe.", flush=True)
        return 1
    print(
        "\n[launch] Browser starting in its own fixed-size profile.\n"
        "First run, do this ONCE in that window:\n"
        "  1) install the FoE Helper extension (Chrome Web Store),\n"
        "  2) log into each world (cz1…cz8),\n"
        "  3) open Guild Battlegrounds on each tab.\n"
        "Then farm:  python -m bap.forge.action.open_targets --worlds worlds_farm.json\n"
        f"(Verify CDP: open http://127.0.0.1:{port}/json/version — it should return JSON.)",
        flush=True)
    return 0


def main(argv=None) -> int:  # pragma: no cover - CLI wiring
    import argparse

    ap = argparse.ArgumentParser(
        prog="bap-forge-launch",
        description="Launch the owned farming browser (fixed window, anti-throttle, persistent).")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, help="persistent profile dir")
    ap.add_argument("--window", default="1536x805", help="window size WxH (fixed → deterministic)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="CDP debug port")
    ap.add_argument("--chrome", default=None, help="path to chrome/chromium (auto-detect if omitted)")
    args = ap.parse_args(argv)
    try:
        w, h = (int(x) for x in args.window.lower().split("x"))
    except Exception:
        print("--window must look like 1536x805", flush=True)
        return 1
    return run_launch(profile=args.profile, window=(w, h), port=args.port, chrome=args.chrome)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
