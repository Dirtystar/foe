"""Percentage-classifier V2 benchmark harness (Milestone 5C) — OBSERVE-ONLY.

Compares candidate percentage classifiers under a **leakage-free, frame-grouped**
evaluation. The production v1 classifier (``bap.forge.detection.classify``) is used
read-only as the baseline and is never modified. No part of this module clicks,
moves the cursor, drives a browser, or changes any threshold/geometry/UI.

Candidate families (see the milestone):

* **A — v1 baseline**: fixed-crop cosine 1-NN, ``MIN_PCT_SIM = 0.70``, top-3 class
  confirmation. The exact production behaviour.
* **B — robust deterministic**: bounded text-centroid re-centring + local contrast
  normalization + translation-tolerant (blurred) cosine 1-NN, still gated by 0.70 +
  confirmation. Uses a *class-independent* bounded recentre — never an unrestricted
  per-exemplar alignment search that maximises similarity across classes.
* **C — compact supervised**: a numpy multinomial logistic regression over the
  normalized crop (deterministic, dependency-free, interpretable). Rejection
  threshold is tuned on the training folds only.

Candidate **D (neural)** is intentionally not built: the data audit (80 %: 0 real
examples, 40 %: 8, 100 %: 5, 65 % of data is 20 %) does not support honest training
of a neural model, and augmentation may not manufacture the missing classes.

Every candidate emits ``(pct, confidence, accepted)``. ``accepted`` is gated so the
safety metric — **wrong-accepted percentage** — can be measured; UNKNOWN is always
preferable to a wrong accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from bap.forge.detection.classify import (
    PercentClassifier,
    _NORM_SIZE,
    _PATCH_DX,
    _PATCH_DY,
    percent_patch,
)
from bap.forge.detection.dataset import battle_map_box, load_all
from bap.forge.detection.scan import MIN_PCT_SIM

# Context-crop window around a badge centre: the v1 nominal window
# (dx -4..66, dy -18..18) padded by ±10 px so candidate B can recentre and the
# robustness benchmark can shift the centre within a single stored crop.
_CTX_DX = (_PATCH_DX[0] - 10, _PATCH_DX[1] + 10)   # (-14, 76) -> width 90
_CTX_DY = (_PATCH_DY[0] - 10, _PATCH_DY[1] + 10)   # (-28, 28) -> height 56
_CTX_W = _CTX_DX[1] - _CTX_DX[0]
_CTX_H = _CTX_DY[1] - _CTX_DY[0]


# --------------------------------------------------------------------------- #
# Crop records                                                                #
# --------------------------------------------------------------------------- #

@dataclass
class CropRecord:
    """One classified badge, with everything a candidate needs and nothing it
    should not see (no held-out leakage lives here — folds are applied later)."""
    frame_key: str
    source: str
    world: str | None
    pct: int
    cx: int
    cy: int
    capture_w: int
    capture_h: int
    ctx: np.ndarray          # (H, W) uint8 grayscale context crop
    v1vec: np.ndarray | None  # exact production percent_patch (normalized) or None
    bvec: np.ndarray | None = None   # cached candidate-B vector (robust, blurred)
    cfeat: np.ndarray | None = None  # cached candidate-C feature (robust, no blur)


def _gray_ctx(img, cx: int, cy: int):
    """Grayscale context crop around (cx, cy); None if it falls off the frame."""
    x0, x1 = cx + _CTX_DX[0], cx + _CTX_DX[1]
    y0, y1 = cy + _CTX_DY[0], cy + _CTX_DY[1]
    h, w = img.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return gray.astype("uint8")


def extract_crops(samples=None) -> list[CropRecord]:
    """Extract a context crop + the exact v1 vector for every classified GT badge.
    Badges whose context crop falls off the frame are skipped (they cannot be
    scored fairly across candidates)."""
    samples = samples if samples is not None else load_all()
    out: list[CropRecord] = []
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        for b in s.badges:
            if b.pct is None:
                continue
            ctx = _gray_ctx(img, b.cx, b.cy)
            if ctx is None:
                continue
            v1 = percent_patch(img, b.cx, b.cy)
            rec = CropRecord(
                frame_key=s.key, source=s.source, world=s.world, pct=int(b.pct),
                cx=b.cx, cy=b.cy, capture_w=s.width, capture_h=s.height,
                ctx=ctx, v1vec=None if v1 is None else v1.astype("float32"),
            )
            rec.bvec = robust_norm(ctx, blur=0.8)
            rec.cfeat = robust_norm(ctx, blur=0.0)
            out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Near-duplicate fold grouping                                                #
# --------------------------------------------------------------------------- #

def _ahash(gray8) -> int:
    """64-bit average hash of an 8x8 reduction (for near-duplicate detection)."""
    small = cv2.resize(gray8, (8, 8), interpolation=cv2.INTER_AREA)
    bits = (small > small.mean()).flatten()
    h = 0
    for bit in bits:
        h = (h << 1) | int(bit)
    return h


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def fold_groups(samples=None, *, near_dup_bits: int = 5) -> dict[str, int]:
    """Map every frame key to a fold-group id. Exact-content duplicates are already
    removed by :func:`load_all`; this additionally unions **near-duplicate**
    screenshots (aHash Hamming distance ``<= near_dup_bits`` over the battle-map
    ROI) into one group so two views of the same battle can never straddle the
    train/test split. A frame with no near-duplicate is its own group."""
    samples = samples if samples is not None else load_all()
    keys, hashes = [], []
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        x, y, w, h = battle_map_box(s)
        roi = cv2.cvtColor(img[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        keys.append(s.key)
        hashes.append(_ahash(roi))

    parent = list(range(len(keys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if _hamming(hashes[i], hashes[j]) <= near_dup_bits:
                union(i, j)

    roots = {}
    groups: dict[str, int] = {}
    for i, k in enumerate(keys):
        r = find(i)
        groups[k] = roots.setdefault(r, len(roots))
    return groups


# --------------------------------------------------------------------------- #
# Preprocessing                                                               #
# --------------------------------------------------------------------------- #

def _l2(v):
    v = v.astype("float32")
    v = v - v.mean()
    n = float(np.linalg.norm(v))
    return None if n < 1e-6 else v / n


def _nominal_from_ctx(ctx):
    """Slice the v1 nominal window out of the context crop (grayscale), matching
    ``percent_patch`` geometry, and return the resized 40x24 grayscale float."""
    x0 = -_CTX_DX[0] + _PATCH_DX[0]
    y0 = -_CTX_DY[0] + _PATCH_DY[0]
    x1 = x0 + (_PATCH_DX[1] - _PATCH_DX[0])
    y1 = y0 + (_PATCH_DY[1] - _PATCH_DY[0])
    win = ctx[y0:y1, x0:x1]
    return cv2.resize(win, _NORM_SIZE, interpolation=cv2.INTER_AREA).astype("float32")


def perturb_ctx(img, cx: int, cy: int, *, dx: int = 0, dy: int = 0,
                scale: float = 1.0, blur: float = 0.0, brightness: float = 0.0,
                contrast: float = 1.0):
    """Extract a context crop under a controlled, *realistic* perturbation for the
    robustness benchmark: integer centre shift (dx, dy), capture-scale change,
    mild blur, and brightness/contrast — the variations a real Chrome capture
    exhibits. No flips or rotations (those change the digit meaning). Returns a
    grayscale context crop the same size as :func:`_gray_ctx`, or None off-frame."""
    # sample a scale-adjusted window then resize back, so `scale` mimics capture
    # resolution differences without changing the stored crop geometry.
    sw = int(round(_CTX_W * scale))
    sh = int(round(_CTX_H * scale))
    ccx, ccy = cx + dx, cy + dy
    x0 = ccx + int(round(_CTX_DX[0] * scale))
    y0 = ccy + int(round(_CTX_DY[0] * scale))
    x1, y1 = x0 + sw, y0 + sh
    h, w = img.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    win = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype("float32")
    if scale != 1.0:
        win = cv2.resize(win, (_CTX_W, _CTX_H), interpolation=cv2.INTER_AREA)
    if contrast != 1.0 or brightness:
        win = np.clip((win - 128.0) * contrast + 128.0 + brightness, 0, 255)
    if blur and blur > 0:
        win = cv2.GaussianBlur(win, (3, 3), blur)
    return np.clip(win, 0, 255).astype("uint8")


def robust_norm(ctx, *, recenter: bool = True, clahe: bool = True, blur: float = 0.8):
    """Candidate-B preprocessing: bounded text-centroid recentre (class-independent),
    local contrast normalization, mild blur for translation tolerance, then the
    v1 normalize. Returns an L2-normalized 40x24 vector (flattened) or None."""
    dx = dy = 0
    if recenter:
        # Foreground = dark text on lighter pill. Threshold on the nominal window,
        # take the centroid, and shift the window by the BOUNDED offset needed to
        # centre it. This never searches for a class-maximising alignment.
        win = _nominal_from_ctx(ctx)
        inv = 255.0 - win
        thr = inv.mean() + inv.std()
        mask = inv > thr
        if mask.sum() >= 8:
            ys, xs = np.nonzero(mask)
            # map centroid (in resized coords) back to raw px, relative to centre
            cxr = (xs.mean() / _NORM_SIZE[0]) * (_PATCH_DX[1] - _PATCH_DX[0]) + _PATCH_DX[0]
            cyr = (ys.mean() / _NORM_SIZE[1]) * (_PATCH_DY[1] - _PATCH_DY[0]) + _PATCH_DY[0]
            # nominal text centre sits ~right of emblem; recentre toward crop mid
            target_x = (_PATCH_DX[0] + _PATCH_DX[1]) / 2.0
            target_y = (_PATCH_DY[0] + _PATCH_DY[1]) / 2.0
            dx = int(round(np.clip(cxr - target_x, -8, 8)))
            dy = int(round(np.clip(cyr - target_y, -8, 8)))
    x0 = -_CTX_DX[0] + _PATCH_DX[0] + dx
    y0 = -_CTX_DY[0] + _PATCH_DY[0] + dy
    x1 = x0 + (_PATCH_DX[1] - _PATCH_DX[0])
    y1 = y0 + (_PATCH_DY[1] - _PATCH_DY[0])
    if x0 < 0 or y0 < 0 or x1 > ctx.shape[1] or y1 > ctx.shape[0]:
        win = _nominal_from_ctx(ctx)
    else:
        win = cv2.resize(ctx[y0:y1, x0:x1], _NORM_SIZE,
                         interpolation=cv2.INTER_AREA).astype("float32")
    u8 = np.clip(win, 0, 255).astype("uint8")
    if clahe:
        u8 = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(u8)
    g = u8.astype("float32")
    if blur and blur > 0:
        g = cv2.GaussianBlur(g, (3, 3), blur)
    return _l2(g.flatten())


def v1_vector(rec: CropRecord):
    """Exact production v1 vector for a record (flattened), or None."""
    if rec.v1vec is None:
        return None
    return rec.v1vec.flatten()


def v1_from_ctx(ctx):
    """Reproduce the production ``percent_patch`` normalized vector (2-D, matching
    ``percent_patch``) from a context crop — used to score v1 on perturbed crops in
    the robustness benchmark."""
    return _l2(_nominal_from_ctx(ctx))


# --------------------------------------------------------------------------- #
# Candidates                                                                  #
# --------------------------------------------------------------------------- #

class _CosineNN:
    """Shared 1-NN cosine core with top-k class confirmation, matching v1's gate."""

    def __init__(self, min_sim: float, k: int = 3, need: int = 2):
        self.min_sim, self.k, self.need = min_sim, k, need
        self._vecs: list[np.ndarray] = []
        self._pcts: list[int] = []

    def fit(self, vecs, pcts):
        self._vecs = [v for v in vecs]
        self._pcts = list(pcts)
        return self

    def _topk(self, v):
        sims = [(self._pcts[i], float(v @ self._vecs[i])) for i in range(len(self._vecs))]
        sims.sort(key=lambda t: -t[1])
        return sims[: self.k]

    def predict(self, v):
        if v is None or not self._vecs:
            return None, 0.0
        top = self._topk(v)
        return top[0][0], top[0][1]

    def accept(self, v):
        if v is None or not self._vecs:
            return False
        top = self._topk(v)
        winner, sim = top[0]
        if sim < self.min_sim:
            return False
        return sum(1 for p, _s in top if p == winner) >= self.need


class CandidateA:
    """Production v1: fixed-crop cosine 1-NN, 0.70 + top-3 confirmation. This is the
    FROZEN baseline — its gate is the production gate and is never tuned."""
    name = "A_v1_fixedcrop_cosine"
    tunable = False   # fixed production gate; not threshold-tuned

    def __init__(self):
        self._clf = PercentClassifier()

    def fit(self, train: list[CropRecord]):
        self._clf.fit([(r.v1vec, r.pct) for r in train if r.v1vec is not None])
        return self

    def _vec(self, rec):
        return None if rec.v1vec is None else rec.v1vec

    def predict(self, rec):
        return self._clf.predict(self._vec(rec))

    score = predict

    def confirm(self, rec):
        return self._clf.confirmed(self._vec(rec))

    def accept(self, rec, threshold: float = MIN_PCT_SIM):
        v = self._vec(rec)
        g, s = self._clf.predict(v)
        return g is not None and s >= MIN_PCT_SIM and self._clf.confirmed(v)


class CandidateB:
    """Robust deterministic: bounded recentre + contrast + translation-tolerant
    cosine 1-NN. Confidence is the nearest cosine; the acceptance threshold is
    tuned on training folds (Step 5), and top-3 confirmation is retained."""
    name = "B_robust_recentre_cosine"
    tunable = True

    def __init__(self):
        self._nn = _CosineNN(MIN_PCT_SIM)

    def fit(self, train: list[CropRecord]):
        vecs = [r.bvec for r in train if r.bvec is not None]
        pcts = [r.pct for r in train if r.bvec is not None]
        self._nn.fit(vecs, pcts)
        return self

    def predict(self, rec):
        return self._nn.predict(rec.bvec)

    score = predict

    def confirm(self, rec):
        if rec.bvec is None or not self._nn._vecs:
            return False
        top = self._nn._topk(rec.bvec)
        winner = top[0][0]
        return sum(1 for p, _s in top if p == winner) >= self._nn.need

    def accept(self, rec, threshold: float = MIN_PCT_SIM):
        pct, conf = self._nn.predict(rec.bvec)
        return pct is not None and conf >= threshold and self.confirm(rec)


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class CandidateC:
    """Compact supervised: numpy multinomial logistic regression on the normalized
    crop. Deterministic (fixed init + iterations). Rejection threshold tuned on the
    training folds only, choosing the smallest confidence that yields zero
    train wrong-accepts (with a safety margin)."""
    name = "C_logreg_numpy"

    def __init__(self, l2: float = 1e-2, iters: int = 400, lr: float = 0.5):
        self.l2, self.iters, self.lr = l2, iters, lr
        self._W = None
        self._b = None
        self._mu = None
        self._sd = None
        self._classes: list[int] = []
        self._thr = 0.5

    @staticmethod
    def _feat(rec):
        return rec.cfeat  # cached robust_norm(blur=0): contrast-normalized 40x24

    def _matrix(self, recs):
        X, y = [], []
        for r in recs:
            f = self._feat(r)
            if f is not None:
                X.append(f)
                y.append(r.pct)
        return np.array(X, dtype="float32"), np.array(y)

    def fit(self, train: list[CropRecord]):
        X, y = self._matrix(train)
        if len(X) == 0:
            self._classes = []
            return self
        self._mu = X.mean(axis=0)
        self._sd = X.std(axis=0) + 1e-6
        Xn = (X - self._mu) / self._sd
        self._classes = sorted(set(int(v) for v in y))
        cls_idx = {c: i for i, c in enumerate(self._classes)}
        Y = np.zeros((len(y), len(self._classes)), dtype="float32")
        for i, v in enumerate(y):
            Y[i, cls_idx[int(v)]] = 1.0
        n, d = Xn.shape
        rng = np.random.RandomState(0)
        self._W = rng.normal(0, 0.01, (d, len(self._classes))).astype("float32")
        self._b = np.zeros(len(self._classes), dtype="float32")
        # class weights counter the heavy 20% imbalance (still cannot invent 80%)
        counts = Y.sum(axis=0)
        cw = (counts.sum() / (len(counts) * np.maximum(counts, 1.0))).astype("float32")
        for _ in range(self.iters):
            P = _softmax(Xn @ self._W + self._b)
            G = (P - Y) * cw
            gW = Xn.T @ G / n + self.l2 * self._W
            gb = G.mean(axis=0)
            self._W -= self.lr * gW
            self._b -= self.lr * gb
        # tune rejection threshold on TRAIN predictions only
        self._thr = self._tune_threshold(Xn, y)
        return self

    def _tune_threshold(self, Xn, y):
        P = _softmax(Xn @ self._W + self._b)
        conf = P.max(axis=1)
        pred = np.array([self._classes[i] for i in P.argmax(axis=1)])
        wrong_conf = conf[(pred != y)]
        if len(wrong_conf):
            return float(min(0.999, wrong_conf.max() + 1e-3))
        return 0.5

    def _prob(self, rec):
        f = self._feat(rec)
        if f is None or self._W is None or not self._classes:
            return None, 0.0
        xn = (f - self._mu) / self._sd
        p = _softmax((xn[None, :] @ self._W + self._b))[0]
        i = int(p.argmax())
        return self._classes[i], float(p[i])

    def predict(self, rec):
        return self._prob(rec)

    score = predict

    def confirm(self, rec):
        return True   # softmax probability is the only gate for C

    def accept(self, rec, threshold: float | None = None):
        pct, conf = self._prob(rec)
        thr = self._thr if threshold is None else threshold
        return pct is not None and conf >= thr

    tunable = True


CANDIDATES = {c.name: c for c in (CandidateA, CandidateB, CandidateC)}


# --------------------------------------------------------------------------- #
# Safety acceptance / rejection layer (Step 5) — tuned on TRAIN folds only     #
# --------------------------------------------------------------------------- #

def _group_kfold(items, group_of, k: int = 5, seed: int = 0):
    """Deterministic grouped k-fold: whole fold-groups are assigned to one split,
    so a group never straddles train/validation."""
    gids = sorted({group_of(x) for x in items})
    rng = np.random.RandomState(seed)
    rng.shuffle(gids)
    assign = {g: i % k for i, g in enumerate(gids)}
    folds = [[] for _ in range(k)]
    for x in items:
        folds[assign[group_of(x)]].append(x)
    return folds


def tune_threshold(candidate_cls, train, groups, *, k: int = 5, margin: float = 1e-3):
    """Pick the smallest acceptance threshold that yields **zero wrong-accepts** on
    grouped out-of-fold predictions over the TRAINING set (maximising correct).
    Returns ``(threshold, oof_stats)``. If even the single most-confident OOF
    prediction is wrong, the threshold is pushed above it so nothing is accepted —
    UNKNOWN is always safe. The held-out frame never participates here."""
    folds = _group_kfold(train, lambda r: groups[r.frame_key], k=k)
    oof = []  # (conf, correct, confirmed)
    for vi in range(len(folds)):
        val = folds[vi]
        tr = [r for j, f in enumerate(folds) if j != vi for r in f]
        if not tr or not val:
            continue
        m = candidate_cls().fit(tr)
        for r in val:
            pct, conf = m.score(r)
            if pct is None:
                continue
            oof.append((float(conf), pct == r.pct, bool(m.confirm(r))))
    usable = [(c, ok) for (c, ok, cf) in oof if cf]
    if not usable:
        return 1.0, {"oof_n": len(oof), "oof_confirmed": 0}
    wrong_confs = [c for (c, ok) in usable if not ok]
    thr = (min(1.0, max(wrong_confs) + margin)) if wrong_confs else 0.0
    n_acc = sum(1 for (c, ok) in usable if c >= thr)
    n_cor = sum(1 for (c, ok) in usable if c >= thr and ok)
    return float(thr), {"oof_n": len(oof), "oof_confirmed": len(usable),
                        "oof_wrong_before": len(wrong_confs),
                        "threshold": round(float(thr), 4),
                        "oof_accepted": n_acc, "oof_correct": n_cor}


def grouped_eval_tuned(candidate_cls, records, groups, *, k: int = 5):
    """Leave-one-fold-group-out with the Step-5 safety layer: for each held-out
    group, tune the acceptance threshold on the remaining (training) records via
    grouped OOF, refit on all training records, then accept held-out predictions
    with that threshold (and the candidate's own confirmation gate)."""
    by_group: dict[int, list[CropRecord]] = {}
    for r in records:
        by_group.setdefault(groups[r.frame_key], []).append(r)
    combined = EvalCounts()
    per_source: dict[str, EvalCounts] = {}
    thresholds = []
    for held, held_recs in by_group.items():
        train = [r for r in records if groups[r.frame_key] != held]
        tunable = getattr(candidate_cls, "tunable", True)
        thr = MIN_PCT_SIM
        if tunable:
            thr, _stats = tune_threshold(candidate_cls, train, groups, k=k)
        thresholds.append(thr)
        model = candidate_cls().fit(train)
        for r in held_recs:
            pred, _conf = model.score(r)
            acc = model.accept(r, thr)
            combined.add(r.pct, pred, acc)
            per_source.setdefault(r.source, EvalCounts()).add(r.pct, pred, acc)
    return combined, per_source, thresholds


# --------------------------------------------------------------------------- #
# Grouped evaluation                                                          #
# --------------------------------------------------------------------------- #

@dataclass
class EvalCounts:
    total: int = 0
    correct: int = 0
    unknown: int = 0
    wrong: int = 0
    confusion: dict = field(default_factory=dict)
    per_class: dict = field(default_factory=dict)   # pct -> [total, correct, wrong, unknown]

    def add(self, gt, pred, accepted):
        self.total += 1
        pc = self.per_class.setdefault(gt, [0, 0, 0, 0])
        pc[0] += 1
        if not accepted:
            self.unknown += 1
            pc[3] += 1
        elif pred == gt:
            self.correct += 1
            pc[1] += 1
        else:
            self.wrong += 1
            pc[2] += 1
            self.confusion[(gt, pred)] = self.confusion.get((gt, pred), 0) + 1

    def to_dict(self):
        return {
            "total": self.total, "correct": self.correct,
            "unknown": self.unknown, "wrong_accepted": self.wrong,
            "correct_rate": round(self.correct / self.total, 3) if self.total else 0.0,
            "unknown_rate": round(self.unknown / self.total, 3) if self.total else 0.0,
            "per_class": {str(k): {"total": v[0], "correct": v[1], "wrong": v[2],
                                   "unknown": v[3]} for k, v in sorted(self.per_class.items())},
            "confusion": {f"{gt}->{pr}": n for (gt, pr), n in sorted(self.confusion.items())},
        }


def grouped_eval(candidate_cls, records: list[CropRecord], groups: dict[str, int]):
    """Leave-one-fold-group-out evaluation. For each fold group, train on all
    records NOT in that group (near-duplicates share a group, so no leakage) and
    predict the held-out records. Reports combined + per-source counts."""
    by_group: dict[int, list[CropRecord]] = {}
    for r in records:
        by_group.setdefault(groups[r.frame_key], []).append(r)

    combined = EvalCounts()
    per_source: dict[str, EvalCounts] = {}
    for held, held_recs in by_group.items():
        train = [r for r in records if groups[r.frame_key] != held]
        model = candidate_cls().fit(train)
        for r in held_recs:
            pred, _conf = model.predict(r)
            acc = model.accept(r)
            combined.add(r.pct, pred, acc)
            per_source.setdefault(r.source, EvalCounts()).add(r.pct, pred, acc)
    return combined, per_source
