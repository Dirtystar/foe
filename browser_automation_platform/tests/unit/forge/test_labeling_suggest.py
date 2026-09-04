import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from bap.forge.labeling import suggest


def _blank(h=1080, w=1920):
    return np.zeros((h, w, 3), np.uint8)


def _put_red(img, cx, cy, r=4):
    # Bright saturated red (BGR) blob of arrow size — stands in for a weakening arrow.
    img[cy - r:cy + r, cx - r:cx + r] = (30, 30, 235)


def test_available():
    assert suggest.available() is True


def test_finds_red_blob_in_game_region():
    img = _blank()
    _put_red(img, 900, 740)
    cands = suggest.suggest_badges(img)
    assert any(abs(cx - 900) <= 8 and abs(cy - 740) <= 8 for cx, cy in cands)


def test_ignores_browser_chrome_region():
    img = _blank()
    _put_red(img, 900, 300)  # above the game content region (chrome)
    assert suggest.suggest_badges(img) == []


def test_ignores_left_black_band():
    img = _blank()
    _put_red(img, 100, 740)  # left of the game content
    assert suggest.suggest_badges(img) == []


def test_ignores_large_red_area():
    img = _blank()
    img[700:900, 800:1200] = (30, 30, 235)  # a big red region, not a badge arrow
    assert suggest.suggest_badges(img) == []


def test_results_sorted_top_to_bottom():
    img = _blank()
    _put_red(img, 1200, 900)
    _put_red(img, 700, 600)
    cands = suggest.suggest_badges(img)
    assert cands == sorted(cands, key=lambda p: (p[1], p[0]))


def test_bad_image_returns_empty():
    assert suggest.suggest_badges("/no/such/file.png") == []
