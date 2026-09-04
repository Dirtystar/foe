"""CDP-targeted click: the clicker dispatches to the page (not the OS), and the loop
performs the right number of clicks / key presses with a stop control. No browser needed."""

from __future__ import annotations

from bap.forge.action.cdp_click import CdpClicker, run_click_loop


class _FakeMouse:
    def __init__(self): self.clicks = []
    def click(self, x, y): self.clicks.append((x, y))


class _FakeKeyboard:
    def __init__(self): self.keys = []
    def press(self, k): self.keys.append(k)


class _FakePage:
    def __init__(self, url="https://cz6.forgeofempires.com/game"):
        self.url = url
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()


class _RecordingClicker:
    def __init__(self): self.clicks = []; self.keys = []
    def click_xy(self, x, y): self.clicks.append((x, y))
    def press(self, k): self.keys.append(k)


# --- CdpClicker dispatches to the page (no OS cursor) ------------------------

def test_clicker_dispatches_click_and_key_to_page():
    page = _FakePage()
    c = CdpClicker(page)
    c.click_xy(913, 521)
    c.press("r")
    assert page.mouse.clicks == [(913, 521)]     # went to the tab, not the desktop
    assert page.keyboard.keys == ["r"]


# --- run_click_loop logic ----------------------------------------------------

def test_loop_single_click_default():
    c = _RecordingClicker()
    n = run_click_loop(c, 10, 20, sleep=lambda s: None)
    assert n == 1 and c.clicks == [(10, 20)] and c.keys == []


def test_loop_repeat_with_key_each_cycle():
    c = _RecordingClicker()
    sleeps = []
    n = run_click_loop(c, 5, 6, key="r", count=3, interval=0.15,
                       sleep=lambda s: sleeps.append(s))
    assert n == 3
    assert c.clicks == [(5, 6)] * 3
    assert c.keys == ["r", "r", "r"]             # R after every click
    assert len(sleeps) == 6                       # interval before key + after, each cycle


def test_loop_stops_when_should_stop_true():
    c = _RecordingClicker()
    calls = {"n": 0}
    def _stop():
        calls["n"] += 1
        return calls["n"] > 2                      # allow 2 clicks, then stop
    n = run_click_loop(c, 1, 2, count=10, sleep=lambda s: None, should_stop=_stop)
    assert n == 2 and len(c.clicks) == 2


def test_loop_zero_or_negative_count_does_nothing():
    c = _RecordingClicker()
    assert run_click_loop(c, 1, 2, count=0, sleep=lambda s: None) == 0
    assert run_click_loop(c, 1, 2, count=-5, sleep=lambda s: None) == 0
    assert c.clicks == []


def test_loop_never_presses_key_when_none():
    c = _RecordingClicker()
    run_click_loop(c, 1, 2, key=None, count=2, sleep=lambda s: None)
    assert c.keys == []
