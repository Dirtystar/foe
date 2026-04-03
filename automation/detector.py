"""
Screen capture and detection for FoE Guild Battle sectors.

Uses Windows PrintWindow API (via capture.py) so each worker can capture
its own browser window even when it is in the background.
"""
import re
import threading

import numpy as np

from .capture import (
    find_window, capture_region as _cap_region,
    capture_window, client_to_screen, is_available as _win32_ok,
)

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False
    print("WARNING: opencv-python not installed. Detection unavailable.")

try:
    import pytesseract
    _TESS_OK = True
except ImportError:
    _TESS_OK = False
    print("WARNING: pytesseract not installed. OCR unavailable.")


# ---------------------------------------------------------------------------
# HSV colour range for the "light blue 20%" sector strip in FoE
# ---------------------------------------------------------------------------
_BLUE_LOWER = np.array([85,  80,  80], dtype=np.uint8)
_BLUE_UPPER = np.array([110, 255, 255], dtype=np.uint8)

_ROW_COVERAGE_THRESH = 0.55
_STRIP_MIN_HEIGHT    = 4
_STRIP_MAX_HEIGHT    = 70

_PSM7_DIGITS = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/"
_PSM7_INT    = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"


class Detector:
    def __init__(self, server_id: str, server_config: dict, tesseract_cmd: str = ""):
        self.server_id   = server_id
        self._cfg        = server_config
        self._tess_cmd   = tesseract_cmd
        self._hwnd_cache: int | None = None
        self._lock       = threading.Lock()

    # ------------------------------------------------------------------
    def update_config(self, server_config: dict) -> None:
        self._cfg = server_config
        with self._lock:
            self._hwnd_cache = None   # force re-lookup on next cycle

    # ------------------------------------------------------------------
    # Window handle lookup
    # ------------------------------------------------------------------
    def _get_hwnd(self) -> int | None:
        with self._lock:
            if self._hwnd_cache and self._is_hwnd_valid(self._hwnd_cache):
                return self._hwnd_cache

        search = self._cfg.get("window_title", "")
        if not search:
            return None

        hwnd = find_window(search)
        with self._lock:
            self._hwnd_cache = hwnd
        return hwnd

    @staticmethod
    def _is_hwnd_valid(hwnd: int) -> bool:
        try:
            import win32gui
            return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Region capture
    # ------------------------------------------------------------------
    def capture_region(self, region: dict) -> "np.ndarray | None":
        if not _win32_ok() or not _CV2_OK:
            return None
        w, h = region.get("w", 0), region.get("h", 0)
        if w <= 0 or h <= 0:
            return None
        hwnd = self._get_hwnd()
        if hwnd is None:
            return None
        return _cap_region(hwnd, region)

    def capture_full_window(self) -> "np.ndarray | None":
        """Capture entire client area — used for calibration screenshots."""
        hwnd = self._get_hwnd()
        if hwnd is None:
            return None
        return capture_window(hwnd)

    # ------------------------------------------------------------------
    # Sector strip detection
    # ------------------------------------------------------------------
    def detect_blue_strip(self) -> bool:
        img = self.capture_region(self._cfg["regions"]["sector_list"])
        if img is None:
            return False

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, _BLUE_LOWER, _BLUE_UPPER)
        row_coverage = np.sum(mask, axis=1) / (mask.shape[1] * 255.0)
        strip_rows = np.where(row_coverage >= _ROW_COVERAGE_THRESH)[0]

        if len(strip_rows) < _STRIP_MIN_HEIGHT:
            return False
        span = int(strip_rows[-1]) - int(strip_rows[0])
        return span <= _STRIP_MAX_HEIGHT

    # ------------------------------------------------------------------
    # OCR helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
        h, w = img_bgr.shape[:2]
        img  = cv2.resize(img_bgr, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        gray  = clahe.apply(gray)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        thresh = cv2.copyMakeBorder(thresh, 10, 10, 10, 10,
                                    cv2.BORDER_CONSTANT, value=255)
        return thresh

    def _ocr(self, img_bgr: np.ndarray, config: str, lang: str = "ces") -> str:
        if not _TESS_OK:
            return ""
        if self._tess_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tess_cmd
        processed = self._preprocess(img_bgr)
        try:
            text = pytesseract.image_to_string(processed, lang=lang, config=config)
            return text.strip().replace(" ", "").replace("\n", "")
        except Exception as e:
            print(f"[{self.server_id}] OCR error: {e}")
            return ""

    # ------------------------------------------------------------------
    def read_fight_counter(self) -> "tuple[int, int] | None":
        img = self.capture_region(self._cfg["regions"]["fight_counter"])
        if img is None:
            return None
        text = self._ocr(img, _PSM7_DIGITS)
        m = re.search(r"(\d+)/(\d+)", text)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def read_oslabeni(self) -> "int | None":
        img = self.capture_region(self._cfg["regions"]["oslabeni"])
        if img is None:
            return None
        text = self._ocr(img, _PSM7_INT)
        m = re.search(r"\d+", text)
        return int(m.group(0)) if m else None

    # ------------------------------------------------------------------
    # Click targets — returns ABSOLUTE screen coordinates
    # ------------------------------------------------------------------
    def _region_center_screen(self, region: dict) -> tuple[int, int]:
        """Return screen coords for the centre of a window-relative region."""
        cx = int(region["x"]) + int(region["w"]) // 2
        cy = int(region["y"]) + int(region["h"]) // 2
        hwnd = self._get_hwnd()
        if hwnd is None:
            return cx, cy
        return client_to_screen(hwnd, cx, cy)

    def find_attack_button(self) -> tuple[int, int]:
        return self._region_center_screen(self._cfg["regions"]["attack_button"])

    def get_click_target(self) -> tuple[int, int]:
        return self._region_center_screen(self._cfg["regions"]["click_target"])
