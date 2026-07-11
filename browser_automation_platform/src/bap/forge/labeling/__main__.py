"""Launch the Forge badge labelling tool.

    python -m bap.forge.labeling <frames_dir> [--labels PATH]

`frames_dir` holds the Forge screenshot PNGs. Labels autosave to
`<frames_dir>/labels.json` unless --labels overrides it, and the tool resumes at
the first unreviewed frame.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bap-forge-label", description="Assisted labelling for Forge weakening badges"
    )
    parser.add_argument("frames_dir", help="directory of Forge screenshot PNGs")
    parser.add_argument(
        "--labels", default=None, metavar="PATH",
        help="labels.json path (default: <frames_dir>/labels.json)",
    )
    args = parser.parse_args(argv)

    frames_dir = Path(args.frames_dir)
    if not frames_dir.is_dir():
        parser.error(f"not a directory: {frames_dir}")
    labels_path = Path(args.labels) if args.labels else frames_dir / "labels.json"

    from bap.forge.labeling.app import run

    return run(str(frames_dir), str(labels_path))


if __name__ == "__main__":
    sys.exit(main())
