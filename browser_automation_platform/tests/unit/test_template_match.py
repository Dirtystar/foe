"""Multi-scale template matcher: it finds a known sprite, at a scale, and refuses noise."""

from __future__ import annotations

import cv2
import numpy as np

from bap.forge.detection.template_match import match_multiscale


def _sprite(seed=0):
    # A smooth, structured sprite (blurred blobs) — like a real building, it survives resize,
    # unlike pure per-pixel noise whose high frequencies vanish when scaled.
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(40, 30, 3), dtype=np.uint8)
    return cv2.GaussianBlur(base, (0, 0), sigmaX=2.5)


def _canvas_with(sprite, at, scale=1.0, size=(400, 500), bg=90):
    img = np.full((size[0], size[1], 3), bg, dtype=np.uint8)
    h, w = sprite.shape[:2]
    s = cv2.resize(sprite, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    y, x = at
    img[y:y + s.shape[0], x:x + s.shape[1]] = s
    return img


def test_finds_sprite_at_native_scale():
    spr = _sprite()
    img = _canvas_with(spr, at=(120, 200))
    m = match_multiscale(img, spr, min_score=0.5)
    assert m is not None
    # centre near (200 + 15, 120 + 20)
    cx, cy = m.center
    assert abs(cx - 215) <= 3 and abs(cy - 140) <= 3
    assert m.score > 0.9


def test_finds_sprite_when_zoomed():
    spr = _sprite(seed=3)
    img = _canvas_with(spr, at=(60, 90), scale=1.3)
    m = match_multiscale(img, spr, min_score=0.5)
    assert m is not None
    assert 1.15 <= m.scale <= 1.45          # recovered ~the right scale
    assert m.score > 0.8


def test_rejects_when_absent():
    spr = _sprite(seed=1)
    other = np.full((300, 300, 3), 70, dtype=np.uint8)   # flat, sprite not present
    m = match_multiscale(other, spr, min_score=0.6)
    assert m is None


def test_anchor_is_below_centre():
    spr = _sprite(seed=2)
    img = _canvas_with(spr, at=(100, 100))
    m = match_multiscale(img, spr, min_score=0.5)
    assert m is not None
    _ax, ay = m.anchor(0.5, 0.6)
    assert ay > m.center[1]                 # 0.6 fraction sits below the centre


def test_empty_inputs_return_none():
    assert match_multiscale(None, _sprite()) is None
    assert match_multiscale(_sprite(), None) is None
    assert match_multiscale(np.zeros((0, 0, 3), np.uint8), _sprite()) is None
