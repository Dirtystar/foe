"""Build the small ZIP that gets handed to the guild.

The repository's working tree is ~444 MB (labelled screenshot datasets, mostly), and the
alerter itself is under half a megabyte. Telling a non-developer to download the whole thing
to run one stdlib app is a bad trade, so this assembles just the closure the alerter imports
plus the sample data, the launchers and the Czech guide.

    python3 packaging/build_alerting_bundle.py            # → dist/FoE-Alerting.zip
    python3 packaging/build_alerting_bundle.py --out /tmp # somewhere else

The file list is deliberately explicit rather than "copy src/bap": an accidental import that
drags in the farmer's clicking code should break this build loudly, not ship quietly. Run
``--verify`` (the default) and it imports the bundle in a subprocess with an empty path to
prove the copy really is self-contained.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Every ``bap`` module the alerter imports, computed once with sys.modules and kept explicit.
MODULES = [
    "bap/__init__.py",
    "bap/alerting/__init__.py",
    "bap/alerting/__main__.py",
    "bap/alerting/clock.py",
    "bap/alerting/config.py",
    "bap/alerting/engine.py",
    "bap/alerting/labels.py",
    "bap/alerting/notifiers.py",
    "bap/alerting/relay.py",
    "bap/alerting/render.py",
    "bap/alerting/schedule.py",
    "bap/alerting/state.py",
    "bap/alerting/watcher.py",
    "bap/alerting/webui.py",
    "bap/forge/__init__.py",
    "bap/forge/gbg_data/__init__.py",
    "bap/forge/gbg_data/advisor.py",
    "bap/forge/gbg_data/live.py",
    "bap/forge/gbg_data/map_layout.py",
    "bap/forge/gbg_data/model.py",
    "bap/forge/gbg_data/parser.py",
]

#: Captured payloads: the map asset drives the labels dropdown, the battleground the preview.
DATA = [
    "dataset/api_samples/getBattleground.sample.json",
    "dataset/api_samples/map_data.volcano_archipelago.sample.json",
]

#: (source, name inside the bundle). The launcher is renamed so it reads as an instruction.
EXTRAS = [
    ("foe-alerting.bat", "SPUSTIT.bat"),
    ("foe-alerting.sh", "spustit.sh"),
    ("docs/navod.html", "NAVOD.html"),
]

README = """FoE Alerting
============

1. Rozbal celou tuhle slozku nekam k sobe (Plocha, Dokumenty).
   Nespoustej nic primo z okna ZIPu - Windows to smaze.

2. Otevri NAVOD.html (dvojklik, otevre se v prohlizeci) a drz se ho.

3. Az budes mit nainstalovany Python: dvojklik na SPUSTIT.bat

Kdyz neco nefunguje, v navodu je tabulka "Kdyz neco nefunguje".
"""


def build(out_dir: Path, *, verify: bool = True) -> Path:
    staging = out_dir / "FoE-Alerting"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "src").mkdir(parents=True)

    missing = [rel for rel in MODULES + DATA if not (REPO / _source(rel)).is_file()]
    if missing:
        raise SystemExit(f"missing from the repo: {', '.join(missing)}")

    for rel in MODULES:
        dest = staging / "src" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "src" / rel, dest)
    for rel in DATA:
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)
    for src, name in EXTRAS:
        shutil.copy2(REPO / src, staging / name)
    (staging / "PRECTI_ME.txt").write_text(README, encoding="utf-8")

    if verify:
        _verify(staging)

    archive = out_dir / "FoE-Alerting.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(out_dir))
    return archive


def _source(rel: str) -> str:
    return f"src/{rel}" if rel.startswith("bap/") else rel


def _verify(staging: Path) -> None:
    """Import the bundle with the repo off sys.path, so a missed file fails here rather than
    on a guild member's PC. Also asserts nothing outside the standard library came along."""
    code = (
        "import json, sys;"
        "sys.path.insert(0, 'src');"
        "import bap.alerting.webui, bap.alerting.__main__, bap.alerting.watcher;"
        "std = set(sys.stdlib_module_names);"
        "tops = {m.split('.')[0] for m in sys.modules if not m.startswith('_')};"
        "print(json.dumps(sorted(t for t in tops if t not in std and t != 'bap')))"
    )
    # -B keeps the check from littering __pycache__ into what we are about to zip.
    out = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=staging,
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"the bundle does not import on its own:\n{out.stderr}")
    extra = [m for m in __import__("json").loads(out.stdout) if m != "sitecustomize"]
    if extra:
        raise SystemExit(f"the bundle pulled in non-stdlib modules: {extra}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the FoE Alerting hand-out ZIP.")
    ap.add_argument("--out", default=str(REPO / "dist"), help="output directory")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the self-contained import check (don't)")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = build(out_dir, verify=not args.no_verify)
    size = archive.stat().st_size
    print(f"{archive}  ({size / 1024:.0f} KB, {len(MODULES)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
