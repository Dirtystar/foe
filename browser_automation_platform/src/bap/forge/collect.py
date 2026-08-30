"""Collect the panel/state frames the app saved while you played, ready to commit.

While the Vision Debugger's **Open Province & Observe State** runs, every observation
is saved as a small bundle under the app's capture folder:

    <data>/forge/captures/
        panel_<ts>/     screen.png  classification.json  context.json   (a confirmed panel)
        unknown_<ts>/   screen.png  classification.json  context.json   (anything else)

This tool has two jobs, both read-only against the game and safe to re-run:

    python -m bap.forge.collect                 # summarise what's been collected
    python -m bap.forge.collect --export        # copy the frames into dataset/panels/

`--export` copies each bundle's screenshot to a descriptively named PNG (plus a
`manifest.csv` row) so you can commit them with "5 - Push.bat". It is idempotent —
frames already exported are skipped, so you can collect a bit, export, push, repeat.
Nothing here plays the game or deletes your captures.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Bundle:
    path: Path
    kind: str              # "panel" | "unknown" | "other"
    ts: str
    observed_state: str
    world: str
    has_image: bool

    def export_name(self) -> str:
        state = (self.observed_state or self.kind or "frame").lower()
        world = self.world or "x"
        return f"{state}_{world}_{self.ts}.png"


def default_captures_dir() -> Path:
    from bap.ops.paths import ensure_dirs, get_paths
    return ensure_dirs(get_paths()).data_dir / "forge" / "captures"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def scan(captures_dir: Path) -> list[Bundle]:
    """Find every capture bundle under ``captures_dir``. Best-effort: a malformed
    bundle is reported with whatever fields survive, never crashes the scan."""
    out: list[Bundle] = []
    if not captures_dir.is_dir():
        return out
    for d in sorted(p for p in captures_dir.iterdir() if p.is_dir()):
        name = d.name
        kind = ("panel" if name.startswith("panel_")
                else "unknown" if name.startswith("unknown_") else "other")
        ts = name.split("_", 1)[1] if "_" in name else name
        ctx = _read_json(d / "context.json")
        out.append(Bundle(
            path=d, kind=kind, ts=ts,
            observed_state=str(ctx.get("observed_state", "")),
            world=str(ctx.get("world", "")),
            has_image=(d / "screen.png").exists(),
        ))
    return out


def summarise(bundles: list[Bundle]) -> str:
    panels = [b for b in bundles if b.kind == "panel"]
    unknowns = [b for b in bundles if b.kind == "unknown"]
    others = [b for b in bundles if b.kind == "other"]
    lines = [
        f"Captured bundles: {len(bundles)}",
        f"  panel   (confirmed PROVINCE_PANEL): {len(panels)}",
        f"  unknown (something else, for review): {len(unknowns)}",
    ]
    if others:
        lines.append(f"  other: {len(others)}")
    worlds = sorted({b.world for b in bundles if b.world})
    if worlds:
        lines.append(f"  worlds seen: {', '.join(worlds)}")
    missing = [b for b in bundles if not b.has_image]
    if missing:
        lines.append(f"  (note: {len(missing)} bundle(s) have no screen.png)")
    return "\n".join(lines)


def export(bundles: list[Bundle], out_dir: Path) -> tuple[int, int]:
    """Copy each bundle's screen.png into ``out_dir`` under a descriptive name and
    append a manifest.csv row. Idempotent: existing targets are skipped. Returns
    (exported, skipped)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.csv"
    new_manifest = not manifest.exists()
    exported = skipped = 0
    with manifest.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_manifest:
            writer.writerow(["filename", "kind", "observed_state", "world",
                             "timestamp", "source_bundle"])
        for b in bundles:
            if not b.has_image:
                continue
            target = out_dir / b.export_name()
            if target.exists():
                skipped += 1
                continue
            try:
                shutil.copy2(b.path / "screen.png", target)
            except Exception:
                skipped += 1
                continue
            writer.writerow([target.name, b.kind, b.observed_state, b.world,
                             b.ts, b.path.name])
            exported += 1
    return exported, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bap-forge-collect",
        description="Summarise or export the panel/state frames collected while playing.")
    parser.add_argument("--captures-dir", default=None, metavar="DIR",
                        help="where the app saved captures (default: <data>/forge/captures)")
    parser.add_argument("--export", action="store_true",
                        help="copy the frames into --out, ready to commit")
    parser.add_argument("--out", default="dataset/panels", metavar="DIR",
                        help="export destination (default: dataset/panels)")
    args = parser.parse_args(argv)

    captures_dir = Path(args.captures_dir) if args.captures_dir else default_captures_dir()
    bundles = scan(captures_dir)

    print(f"Captures folder: {captures_dir}")
    if not bundles:
        print("Nothing collected yet. In the Vision Debugger, open a live World and "
              "click 'Open Province & Observe State' on a few provinces, then re-run this.")
        return 0
    print(summarise(bundles))

    if not args.export:
        print("\nRun with --export to copy these frames into a folder you can commit.")
        return 0

    out_dir = Path(args.out)
    exported, skipped = export(bundles, out_dir)
    print(f"\nExported {exported} new frame(s) to {out_dir}"
          + (f" ({skipped} already there — skipped)." if skipped else "."))
    if exported:
        print("Next: commit them and run '5 - Push.bat' (or `git add` + push) to send "
              "them to Radek.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
