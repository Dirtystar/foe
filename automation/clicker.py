"""
Mouse/keyboard automation via CDP.
Clicks and keypresses are dispatched directly into the browser tab —
no need for the window to be visible or focused.
"""
import time


def click_once(session, x: int, y: int) -> None:
    session.click(x, y)


def press_r(session) -> None:
    session.key_press("r")


def fast_click_loop(
    session,
    x: int,
    y: int,
    interval_ms: int,
    r_every_n: int,
    stop_event,
    max_duration_s: float = 30.0,
) -> int:
    """
    Rapidly click at (x, y) via CDP, pressing 'r' every r_every_n clicks.
    Returns the number of clicks performed.
    """
    count      = 0
    start      = time.monotonic()
    interval_s = max(interval_ms, 0) / 1000.0

    while not stop_event.is_set():
        if time.monotonic() - start > max_duration_s:
            break
        session.click(x, y)
        count += 1
        if r_every_n > 0 and count % r_every_n == 0:
            session.key_press("r")
        if interval_s > 0:
            time.sleep(interval_s)

    return count
