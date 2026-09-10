"""Percentage classification without OCR.

The badge shows one of five fixed percentages (20/40/60/80/100). Rather than run
an OCR engine, this matches the pill's percentage patch against labelled
exemplar patches (nearest-neighbour by cosine similarity on a normalised
grayscale crop). Exemplars come from the human-confirmed grading set, so the
classifier is graded honestly by leave-one-out.

The percentage text sits just right of the emblem centre; `percent_patch`
extracts that region relative to a detection/ground-truth centre.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import cv2
    import numpy as np

    _CV = True
except Exception:  # pragma: no cover
    _CV = False

# Percentage patch geometry relative to the emblem centre, and the normalised
# size everything is compared at.
_PATCH_DX = (-4, 66)   # x range around centre (emblem + "XX%")
_PATCH_DY = (-18, 18)  # y range
_NORM_SIZE = (40, 24)  # (w, h) all patches are resized to


def percent_patch(image, cx: int, cy: int):
    """Return the normalised grayscale percentage patch around (cx, cy), or None
    if it falls outside the image. Deterministic and OCR-free."""
    if not _CV:  # pragma: no cover
        return None
    x0, x1 = cx + _PATCH_DX[0], cx + _PATCH_DX[1]
    y0, y1 = cy + _PATCH_DY[0], cy + _PATCH_DY[1]
    h, w = image.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
        return None
    patch = image[y0:y1, x0:x1]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, _NORM_SIZE, interpolation=cv2.INTER_AREA).astype("float32")
    gray -= gray.mean()
    norm = float(np.linalg.norm(gray))
    if norm < 1e-6:
        return None
    return gray / norm


@dataclass
class _Exemplar:
    vec: object  # normalised patch vector
    pct: int


class PercentClassifier:
    """1-NN cosine classifier over labelled percentage patches."""

    def __init__(self) -> None:
        self._exemplars: list[_Exemplar] = []

    def __len__(self) -> int:
        return len(self._exemplars)

    def fit(self, examples: list[tuple[object, int]]) -> "PercentClassifier":
        """`examples` is a list of (normalised_patch, pct). Patches that are None
        are skipped (out-of-frame)."""
        self._exemplars = [_Exemplar(vec=v, pct=int(p)) for v, p in examples if v is not None]
        return self

    def predict(self, patch) -> tuple[int | None, float]:
        """Return (pct, similarity) for the nearest exemplar, or (None, 0.0) if
        the classifier is empty or the patch is None. This is the raw 1-NN — the
        acceptance gate additionally requires :meth:`confirmed` (see below)."""
        if patch is None or not self._exemplars:
            return None, 0.0
        best_pct, best_sim = None, -1.0
        for ex in self._exemplars:
            sim = float((patch * ex.vec).sum())  # cosine (both unit-norm)
            if sim > best_sim:
                best_sim, best_pct = sim, ex.pct
        return best_pct, best_sim

    def confirmed(self, patch, *, k: int = 3, need: int = 2) -> bool:
        """Class-conditioned nearest-neighbour confirmation (Milestone 5B): the
        nearest exemplar's class must be shared by at least ``need`` of the ``k``
        nearest exemplars. A lone near neighbour of one class is NOT enough.

        This is a **safety** gate layered on top of the ``similarity >= MIN_PCT_SIM``
        bar (it does not change that bar). Measured motivation: after new live
        exemplars were added, two isolated cross-class matches (a 40% crop and a
        60% crop from different capture scales) reached ~0.702 similarity and were
        wrong-accepted; requiring a second same-class neighbour removes both without
        lowering the threshold. Returns False for an empty classifier / None patch."""
        top = self.predict_topk(patch, k)
        if not top:
            return False
        winner = top[0][0]
        return sum(1 for pct, _sim in top if pct == winner) >= need

    def predict_topk(self, patch, k: int = 5) -> list[tuple[int, float]]:
        """The k nearest labelled exemplars as (pct, similarity), best first —
        for diagnosing why a badge reads as UNKNOWN. Empty if the classifier is
        empty or the patch is None."""
        if patch is None or not self._exemplars:
            return []
        scored = sorted(
            ((ex.pct, float((patch * ex.vec).sum())) for ex in self._exemplars),
            key=lambda t: -t[1],
        )
        return scored[:k]

    def nearest(self, patch, k: int = 5) -> list[tuple[int, float, object]]:
        """The k nearest exemplars as (pct, similarity, image), best first, where
        image is the exemplar's normalized vector rendered back to an 8-bit grid —
        for a side-by-side contact sheet against the live crop."""
        if patch is None or not self._exemplars:
            return []
        scored = sorted(self._exemplars, key=lambda ex: -float((patch * ex.vec).sum()))[:k]
        return [(ex.pct, float((patch * ex.vec).sum()), vec_to_image(ex.vec)) for ex in scored]


def vec_to_image(vec):
    """Render a normalized patch/exemplar vector back to an 8-bit grayscale image
    (the classifier's `_NORM_SIZE` grid) for inspection/contact sheets."""
    if not _CV:  # pragma: no cover
        return None
    arr = np.asarray(vec, dtype="float32")
    if arr.ndim == 1:
        arr = arr.reshape(_NORM_SIZE[1], _NORM_SIZE[0])  # (h, w)
    arr = arr - arr.min()
    span = float(arr.max()) or 1.0
    return (arr / span * 255).astype("uint8")


def _examples_from(frames_dir, labels_path) -> list[tuple[object, int]]:
    from pathlib import Path

    from bap.forge.labeling.model import LabelStore

    frames_dir = Path(frames_dir)
    store = LabelStore.load(labels_path)
    out: list[tuple[object, int]] = []
    for name in store.files():
        fl = store.get(name)
        if fl is None or not fl.reviewed:
            continue
        img = cv2.imread(str(frames_dir / name))
        if img is None:
            continue
        for b in fl.badges:
            if b.pct is not None:
                out.append((percent_patch(img, b.cx, b.cy), b.pct))
    return out


def train_from_labels(frames_dir, labels_path) -> PercentClassifier | None:
    """Build a classifier from every classified badge in one reviewed label set.
    Returns None if OpenCV is missing or nothing is reviewed/classified yet."""
    if not _CV:  # pragma: no cover
        return None
    examples = _examples_from(frames_dir, labels_path)
    return PercentClassifier().fit(examples) if examples else None


def default_assets_root():
    """Locate ``tests/forge_assets`` robustly by walking up from this module.

    The reviewed label sets live at the **repository root** under
    ``tests/forge_assets``; this file is at ``src/bap/forge/detection/``, so a
    fixed ``parents[N]`` index is fragile (it silently resolved to
    ``src/tests/forge_assets`` before — a directory that does not exist — which
    left the bundled classifier empty and every live percentage UNKNOWN). Walking
    up until the directory is found is layout- and cwd-independent. Returns
    ``None`` when the datasets are not on disk (e.g. an installed wheel that does
    not ship ``tests/``)."""
    from pathlib import Path

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "tests" / "forge_assets"
        if candidate.is_dir():
            return candidate
    return None


def default_snapshot_dataset_dir():
    """Locate THE one canonical reviewed dataset (frames/ + labels.json) that every
    Review-from-the-UI action edits and that "Import Snapshot into Dataset" writes to.

    Delegates to :func:`bap.forge.dataset_store.reviewed_dataset_dir` so training,
    evaluation, the GUI, snapshot import, and this loader all agree on a single
    location (Milestone 4.15). It is a **first-class reviewed source** alongside
    grading / live_review / review_batch. Returns ``None`` only when that dataset
    has not been created yet (no labels.json on disk), so an empty checkout adds
    nothing rather than erroring."""
    from bap.forge.dataset_store import reviewed_dataset_dir

    candidate = reviewed_dataset_dir()
    if (candidate / "labels.json").exists() and (candidate / "frames").is_dir():
        return candidate
    return None


def default_label_sources(assets_root) -> list[tuple]:
    """The reviewed label sets — grading, live review, the reviewed active-learning
    batch (all under ``assets_root``), plus the repo-root ``dataset/`` of imported
    snapshots — as ``(frames_dir, labels_path)`` pairs. A source is included only
    when its labels.json is present, so an imported snapshot joins automatically.
    Single source of truth for both the bundled classifier and the retrain path.
    Only reviewed, classified badges become exemplars (see ``_examples_from``), so
    an imported-but-not-yet-reviewed frame contributes nothing until reviewed."""
    from pathlib import Path

    root = Path(assets_root)
    out = []
    for name in ("grading", "live_review", "review_batch_002"):
        base = root / name
        if (base / "labels.json").exists():
            out.append((base / "frames", base / "labels.json"))
    snapshot_dir = default_snapshot_dataset_dir()
    if snapshot_dir is not None:
        out.append((snapshot_dir / "frames", snapshot_dir / "labels.json"))
    return out


def train_from_sources(sources) -> PercentClassifier | None:
    """Build one classifier from several reviewed label sets — used to fold the
    reviewed **live** crops in alongside the historical grading set, so live-scale
    badges have same-scale exemplars to match against. `sources` is an iterable of
    ``(frames_dir, labels_path)``."""
    if not _CV:  # pragma: no cover
        return None
    examples: list[tuple[object, int]] = []
    for frames_dir, labels_path in sources:
        try:
            examples.extend(_examples_from(frames_dir, labels_path))
        except Exception:
            continue
    return PercentClassifier().fit(examples) if examples else None


__all__ = ["PercentClassifier", "percent_patch", "train_from_labels",
           "train_from_sources", "default_label_sources", "default_assets_root",
           "vec_to_image"]
