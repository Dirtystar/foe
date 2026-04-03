"""
Windows-native window capture using PrintWindow API.
Works even when the window is in the background or behind other windows.
Falls back gracefully on non-Windows platforms.
"""
import numpy as np

try:
    import win32gui
    import win32ui
    import win32con
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False


def is_available() -> bool:
    return _WIN32_OK


def list_windows(search: str = "") -> list[dict]:
    """Return list of {hwnd, title} for all visible windows matching search."""
    if not _WIN32_OK:
        return []
    results = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if not search or search.lower() in title.lower():
            results.append({"hwnd": hwnd, "title": title})

    win32gui.EnumWindows(cb, None)
    return results


def find_window(search: str) -> int | None:
    """Find the first visible window whose title contains search (case-insensitive)."""
    results = list_windows(search)
    return results[0]["hwnd"] if results else None


def capture_window(hwnd: int) -> np.ndarray | None:
    """
    Capture the client area of a window using PrintWindow.
    Returns BGR uint8 numpy array, or None on failure.
    Works even when the window is in the background.
    """
    if not _WIN32_OK:
        return None
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # PW_CLIENTONLY = 1  →  capture client area only (no title bar / borders)
        win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 1)

        bmp_info = bmp.GetInfo()
        bmp_data = bmp.GetBitmapBits(True)

        img = np.frombuffer(bmp_data, dtype=np.uint8).reshape(
            (bmp_info["bmHeight"], bmp_info["bmWidth"], 4)
        )
        img = img[:, :, :3].copy()   # BGRA → BGR, make writable

        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        win32ui.DeleteObject(bmp.GetHandle())

        return img

    except Exception as e:
        print(f"capture_window error (hwnd={hwnd}): {e}")
        return None


def capture_region(hwnd: int, region: dict) -> np.ndarray | None:
    """
    Capture a sub-region (relative to window client area) from a window.
    region = {x, y, w, h}  — all in client-area pixels.
    """
    if not _WIN32_OK:
        return None
    w, h = region.get("w", 0), region.get("h", 0)
    if w <= 0 or h <= 0:
        return None

    full = capture_window(hwnd)
    if full is None:
        return None

    x, y = int(region["x"]), int(region["y"])
    x2, y2 = x + int(w), y + int(h)

    # Clamp to actual image bounds
    img_h, img_w = full.shape[:2]
    x  = max(0, min(x,  img_w))
    y  = max(0, min(y,  img_h))
    x2 = max(0, min(x2, img_w))
    y2 = max(0, min(y2, img_h))

    if x2 <= x or y2 <= y:
        return None
    return full[y:y2, x:x2]


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """Convert client-area coordinates to absolute screen coordinates."""
    if not _WIN32_OK:
        return x, y
    try:
        sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
        return sx, sy
    except Exception:
        return x, y
