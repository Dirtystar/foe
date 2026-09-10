"""Milestone 5C — percentage-classifier V2 benchmark harness invariants.

These pin the *experimental* benchmark's safety and leakage properties. Nothing
here promotes a v2 classifier; the production v1 path is untouched.
"""

from __future__ import annotations

import inspect

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.forge.research import classifier_bench as B


# --- preprocessing determinism + bounded, label-preserving augmentation ------

def _rand_ctx(seed=0):
    return np.random.RandomState(seed).randint(0, 255, (B._CTX_H, B._CTX_W), np.uint8)


def test_robust_norm_is_deterministic():
    ctx = _rand_ctx(1)
    a = B.robust_norm(ctx)
    b = B.robust_norm(ctx)
    assert a is not None and np.array_equal(a, b)


def test_v1_from_ctx_matches_percent_patch_shape_and_norm():
    ctx = _rand_ctx(2)
    v = B.v1_from_ctx(ctx)
    assert v.shape == (B._NORM_SIZE[1], B._NORM_SIZE[0])  # 2-D like percent_patch
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-4     # L2-normalized


def test_perturb_identity_matches_plain_ctx():
    img = np.random.RandomState(3).randint(0, 255, (400, 400, 3), np.uint8)
    cx, cy = 200, 200
    plain = B._gray_ctx(img, cx, cy)
    same = B.perturb_ctx(img, cx, cy, dx=0, dy=0, scale=1.0)
    assert same is not None and np.array_equal(plain, same)


def test_perturb_does_not_flip_or_rotate():
    # A horizontal gradient must stay left->bright-right after perturbation
    # (a flip/rotation would reverse it). Only translation/scale/blur/contrast
    # are allowed — never orientation changes that alter the digit meaning.
    img = np.tile(np.linspace(0, 255, 400, dtype=np.uint8), (400, 1))
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    out = B.perturb_ctx(img, 200, 200, dx=2, dy=1, blur=1.0, contrast=1.1)
    assert out is not None
    assert out[:, -1].mean() > out[:, 0].mean()  # right still brighter than left


def test_robust_norm_recenter_shift_is_bounded():
    # The bounded text-centroid recentre may never exceed +/-8 px (never an
    # unrestricted alignment search). Probe the internal clamp via source contract.
    src = inspect.getsource(B.robust_norm)
    assert "np.clip(cxr - target_x, -8, 8)" in src
    assert "np.clip(cyr - target_y, -8, 8)" in src


# --- UNKNOWN rejection + safe failure ----------------------------------------

def test_cosine_nn_rejects_below_threshold_and_when_empty():
    nn = B._CosineNN(min_sim=0.9)
    assert nn.accept(np.ones(10, np.float32)) is False   # empty bank -> UNKNOWN
    v20 = np.zeros(10, np.float32); v20[0] = 1.0
    nn.fit([v20, v20], [20, 20])
    orth = np.zeros(10, np.float32); orth[1] = 1.0
    assert nn.accept(orth) is False                       # sim 0 < 0.9 -> UNKNOWN


def test_candidate_accept_supports_unknown_rejection():
    ctx = _rand_ctx(4)
    rec = B.CropRecord(frame_key="s:f", source="historical", world=None, pct=20,
                       cx=0, cy=0, capture_w=1920, capture_h=1080, ctx=ctx,
                       v1vec=B.v1_from_ctx(ctx), bvec=B.robust_norm(ctx),
                       cfeat=B.robust_norm(ctx, blur=0.0))
    b = B.CandidateB().fit([rec, rec])
    assert b.accept(rec, threshold=1.01) is False         # impossible bar -> UNKNOWN


def test_missing_model_fails_to_unknown():
    ctx = _rand_ctx(5)
    rec = B.CropRecord(frame_key="s:f", source="historical", world=None, pct=20,
                       cx=0, cy=0, capture_w=1920, capture_h=1080, ctx=ctx,
                       v1vec=None, bvec=B.robust_norm(ctx), cfeat=B.robust_norm(ctx, blur=0.0))
    # empty-trained candidates must never accept
    assert B.CandidateA().fit([]).accept(rec) is False
    assert B.CandidateB().fit([]).accept(rec, 0.0) is False
    c = B.CandidateC().fit([])       # no classes learned
    assert c.accept(rec) is False


# --- near-duplicate grouping + leakage-free folds -----------------------------

def test_ahash_groups_near_duplicates():
    base = np.random.RandomState(6).randint(0, 255, (64, 64), np.uint8)
    noisy = np.clip(base.astype(int) + np.random.RandomState(7).randint(-4, 4, base.shape), 0, 255).astype(np.uint8)
    far = np.random.RandomState(8).randint(0, 255, (64, 64), np.uint8)
    assert B._hamming(B._ahash(base), B._ahash(noisy)) <= 5
    assert B._hamming(B._ahash(base), B._ahash(far)) > 5


def _synth_records():
    recs = []
    for fk, pct, n in [("s:a", 20, 3), ("s:b", 60, 3), ("s:c", 20, 2), ("s:d", 60, 2)]:
        for i in range(n):
            ctx = _rand_ctx(hash((fk, i)) % 1000)
            recs.append(B.CropRecord(frame_key=fk, source="historical", world=None,
                        pct=pct, cx=0, cy=0, capture_w=1920, capture_h=1080, ctx=ctx,
                        v1vec=B.v1_from_ctx(ctx), bvec=B.robust_norm(ctx),
                        cfeat=B.robust_norm(ctx, blur=0.0)))
    return recs


def test_grouped_eval_has_no_same_group_leakage():
    recs = _synth_records()
    groups = {"s:a": 0, "s:b": 1, "s:c": 0, "s:d": 1}  # a & c share a fold group

    seen_train_groups = {}

    class _Spy:
        tunable = False
        def fit(self, train):
            self._g = {groups[r.frame_key] for r in train}
            return self
        def predict(self, rec):
            # record which held group is being predicted vs the training groups
            seen_train_groups[groups[rec.frame_key]] = set(self._g)
            return rec.pct, 1.0
        score = predict
        def confirm(self, rec):
            return True
        def accept(self, rec, threshold=0.0):
            return False

    B.grouped_eval(_Spy, recs, groups)
    # the held-out group must never appear in the training groups for its own fold
    for held, train_groups in seen_train_groups.items():
        assert held not in train_groups


def test_wrong_accepted_metric_is_counted():
    c = B.EvalCounts()
    c.add(20, 20, True)    # correct
    c.add(20, 60, True)    # wrong-accepted
    c.add(40, 40, False)   # unknown
    d = c.to_dict()
    assert d["correct"] == 1 and d["wrong_accepted"] == 1 and d["unknown"] == 1
    assert d["confusion"] == {"20->60": 1}


# --- production v1 is untouched + no cursor/click reachable --------------------

def test_research_module_does_not_reach_cursor_or_click():
    # No output-side capability may be reachable from the benchmark. Check the
    # executable code (imports + call sites), not the docstring prose, which is
    # allowed to *describe* that it never moves the cursor.
    import ast

    tree = ast.parse(inspect.getsource(B))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for mod in imported:
        assert "cursor" not in mod and "pyautogui" not in mod, f"forbidden import {mod!r}"
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for forbidden in ("move_to", "click", "press", "type"):
        assert forbidden not in calls, f"benchmark must not call {forbidden!r}"


def test_importing_research_does_not_change_v1_classifier():
    # v1 remains the fixed-crop cosine 1-NN with the 0.70 + confirm gate.
    from bap.forge.detection.classify import PercentClassifier
    p20 = np.zeros(24 * 40, np.float32); p20[0] = 1.0
    p60 = np.zeros(24 * 40, np.float32); p60[-1] = 1.0
    clf = PercentClassifier().fit([(p20, 20), (p60, 60)])
    assert clf.predict(p20)[0] == 20
    assert clf.confirmed(p20) is False   # lone neighbour -> unconfirmed (M5B gate)
