"""
Fast mouse/keyboard automation for FoE Guild Battle.

Key speed optimisations applied:
  - pyautogui.PAUSE = 0   (removes default 0.1s inter-action delay)
  - pyautogui.FAILSAFE = False  (no corner-detection overhead)
  - time.sleep only if interval_ms > 0
"""
import time

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    _PYAUTOGUI_OK = True
except Exception as _e:
    _PYAUTOGUI_OK = False
    print(f"WARNING: pyautogui not available: {_e}")


def _check() -> None:
    if not _PYAUTOGUI_OK:
        raise RuntimeError("pyautogui is not installed or could not be imported.")


def click_once(x: int, y: int) -> None:
    _check()
    pyautogui.click(x, y)


def press_r() -> None:
    _check()
    pyautogui.press("r")


def move_to(x: int, y: int) -> None:
    _check()
    pyautogui.moveTo(x, y, duration=0)


def fast_click_loop(
    x: int,
    y: int,
    interval_ms: int,
    r_every_n: int,
    stop_event,
    max_duration_s: float = 30.0,
) -> int:
    """
    Rapidly click at (x, y), pressing 'r' every r_every_n clicks.

    Returns the number of clicks performed.
    Exits early if stop_event.is_set() or max_duration_s is exceeded.
    """
    _check()
    count = 0
    start = time.monotonic()
    interval_s = max(interval_ms, 0) / 1000.0

    while not stop_event.is_set():
        if time.monotonic() - start > max_duration_s:
            break
        pyautogui.click(x, y)
        count += 1
        if r_every_n > 0 and count % r_every_n == 0:
            pyautogui.press("r")
        if interval_s > 0:
            time.sleep(interval_s)

    return count
