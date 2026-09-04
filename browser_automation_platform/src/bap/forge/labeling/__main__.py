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
    labels_path = Path(args.labels) if args.labels else default_labels_path(frames_dir)

    from bap.forge.labeling.app import run

    return run(str(frames_dir), str(labels_path))


def default_labels_path(frames_dir: Path) -> Path:
    """Canonical labels location for a frames directory.

    A grading set is laid out as ``<set>/frames/*.png`` with ``<set>/labels.json``
    beside the frames folder — never inside it. So when the frames live in a
    directory named ``frames`` (or a ``labels.json`` already sits in the parent),
    autosave targets the parent's ``labels.json``; otherwise it sits next to the
    frames. This stops the tool from silently creating a stray duplicate inside
    ``frames/``.
    """
    parent_labels = frames_dir.parent / "labels.json"
    if frames_dir.name == "frames" or parent_labels.exists():
        return parent_labels
    return frames_dir / "labels.json"


if __name__ == "__main__":
    sys.exit(main())
