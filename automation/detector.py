"""
Screen capture and detection for FoE Guild Battle sectors.
Uses CDP screenshot — works on background tabs, identified by URL.
"""
import re
import numpy as np
from io import BytesIO

try:
    from PIL import Image as _PILImage
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
    print("WARNING: Pillow not installed.")

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


_BLUE_LOWER = np.array([85,  80,  80], dtype=np.uint8)
_BLUE_UPPER = np.array([110, 255, 255], dtype=np.uint8)

_ROW_COVERAGE_THRESH = 0.55
_STRIP_MIN_HEIGHT    = 4
_STRIP_MAX_HEIGHT    = 70

_PSM7_DIGITS = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/"
_PSM7_INT    = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"


def _png_to_bgr(png_bytes: bytes) -> "np.ndarray | None":
    if not _PIL_OK or not _CV2_OK:
        return None
    try:
        img = _PILImage.open(BytesIO(png_bytes)).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        return arr[:, :, ::-1]   # RGB → BGR
    except Exception:
        return None


class Detector:
    def __init__(self, server_id: str, server_config: dict, tesseract_cmd: str = ""):
        self.server_id  = server_id
        self._cfg       = server_config
        self._tess_cmd  = tesseract_cmd
        self._session   = None   # CdpSession, injected by worker

    def set_session(self, session) -> None:
        self._session = session

    def update_config(self, server_config: dict) -> None:
        self._cfg = server_config

    # ------------------------------------------------------------------
    # Full-window capture (returns BGR numpy array)
    # ------------------------------------------------------------------
    def _grab_full(self) -> "np.ndarray | None":
        if self._session is None:
            return None
        png = self._session.screenshot_png()
        if png is None:
            return None
        return _png_to_bgr(png)

    def capture_full_window(self) -> "np.ndarray | None":
        return self._grab_full()

    # ------------------------------------------------------------------
    # Region crop from full screenshot
    # ------------------------------------------------------------------
    def capture_region(self, region: dict) -> "np.ndarray | None":
        w, h = region.get("w", 0), region.get("h", 0)
        if w <= 0 or h <= 0:
            return None
        full = self._grab_full()
        if full is None:
            return None
        x, y = int(region["x"]), int(region["y"])
        img_h, img_w = full.shape[:2]
        x2, y2 = min(x + int(w), img_w), min(y + int(h), img_h)
        if x2 <= x or y2 <= y:
            return None
        return full[y:y2, x:x2]

    # ------------------------------------------------------------------
    # Blue-strip sector detection
    # ------------------------------------------------------------------
    def detect_blue_strip(self) -> bool:
        img = self.capture_region(self._cfg["regions"]["sector_list"])
        if img is None:
            return False
        hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, _BLUE_LOWER, _BLUE_UPPER)
        row_coverage = np.sum(mask, axis=1) / (mask.shape[1] * 255.0)
        strip_rows   = np.where(row_coverage >= _ROW_COVERAGE_THRESH)[0]
        if len(strip_rows) < _STRIP_MIN_HEIGHT:
            return False
        return (int(strip_rows[-1]) - int(strip_rows[0])) <= _STRIP_MAX_HEIGHT

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    @staticmethod
    def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
        h, w  = img_bgr.shape[:2]
        img   = cv2.resize(img_bgr, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        gray  = clahe.apply(gray)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        return cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

    def _ocr(self, img_bgr: np.ndarray, config: str, lang: str = "ces") -> str:
        if not _TESS_OK:
            return ""
        if self._tess_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tess_cmd
        try:
            text = pytesseract.image_to_string(self._preprocess(img_bgr), lang=lang, config=config)
            return text.strip().replace(" ", "").replace("\n", "")
        except Exception as e:
            print(f"[{self.server_id}] OCR error: {e}")
            return ""

    def read_fight_counter(self) -> "tuple[int, int] | None":
        img = self.capture_region(self._cfg["regions"]["fight_counter"])
        if img is None:
            return None
        m = re.search(r"(\d+)/(\d+)", self._ocr(img, _PSM7_DIGITS))
        return (int(m.group(1)), int(m.group(2))) if m else None

    def read_oslabeni(self) -> "int | None":
        img = self.capture_region(self._cfg["regions"]["oslabeni"])
        if img is None:
            return None
        m = re.search(r"\d+", self._ocr(img, _PSM7_INT))
        return int(m.group(0)) if m else None

    # ------------------------------------------------------------------
    # Click targets — in screenshot-pixel coordinates
    # ------------------------------------------------------------------
    def find_attack_button(self) -> tuple[int, int]:
        r = self._cfg["regions"]["attack_button"]
        return (int(r["x"]) + int(r["w"]) // 2, int(r["y"]) + int(r["h"]) // 2)

    def get_click_target(self) -> tuple[int, int]:
        r = self._cfg["regions"]["click_target"]
        return (int(r["x"]) + int(r["w"]) // 2, int(r["y"]) + int(r["h"]) // 2)
