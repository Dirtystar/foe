"""
Screen capture and detection for FoE Guild Battle sectors.

Each Detector instance owns its own mss.mss() context (NOT thread-shared).
"""
import re
import threading

import numpy as np

try:
    import mss as _mss_mod
    _MSS_OK = True
except ImportError:
    _MSS_OK = False
    print("WARNING: mss not installed. Screen capture unavailable.")

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
# Hue 85-110 = cyan-blue; adjust if colours look different on your monitor
# ---------------------------------------------------------------------------
_BLUE_LOWER = np.array([85,  80,  80], dtype=np.uint8)
_BLUE_UPPER = np.array([110, 255, 255], dtype=np.uint8)

# Minimum fraction of a row that must be blue to count as a strip row
_ROW_COVERAGE_THRESH = 0.55

# Strip geometry constraints (in pixels)
_STRIP_MIN_HEIGHT = 4
_STRIP_MAX_HEIGHT = 70

# OCR Tesseract page-seg-mode for single lines
_PSM7_DIGITS = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/"
_PSM7_INT    = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"


class Detector:
    def __init__(self, server_id: str, server_config: dict, tesseract_cmd: str = ""):
        self.server_id = server_id
        self._cfg = server_config          # reference; re-read on each cycle via worker
        self._tess_cmd = tesseract_cmd
        self._sct = None                   # lazy-init inside worker thread
        self._sct_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Config hot-reload
    # ------------------------------------------------------------------
    def update_config(self, server_config: dict) -> None:
        self._cfg = server_config

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------
    def _get_sct(self):
        if self._sct is None:
            if not _MSS_OK:
                raise RuntimeError("mss not available")
            self._sct = _mss_mod.mss()
        return self._sct

    def capture_region(self, region: dict) -> "np.ndarray | None":
        """Capture an absolute screen region. Returns BGR uint8 array or None."""
        if not _MSS_OK or not _CV2_OK:
            return None
        w, h = region.get("w", 0), region.get("h", 0)
        if w <= 0 or h <= 0:
            return None
        monitor = {
            "left":   int(region["x"]),
            "top":    int(region["y"]),
            "width":  int(w),
            "height": int(h),
        }
        try:
            sct = self._get_sct()
            raw = sct.grab(monitor)
            # mss returns BGRA; drop alpha
            arr = np.array(raw, dtype=np.uint8)
            return arr[:, :, :3]
        except Exception as e:
            print(f"[{self.server_id}] capture_region error: {e}")
            return None

    # ------------------------------------------------------------------
    # Sector strip detection (light blue 20% strip)
    # ------------------------------------------------------------------
    def detect_blue_strip(self) -> bool:
        """
        Returns True if a horizontal light-blue strip (the '20%' indicator)
        is found in the sector_list region.
        """
        img = self.capture_region(self._cfg["regions"]["sector_list"])
        if img is None:
            return False

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, _BLUE_LOWER, _BLUE_UPPER)

        # Fraction of blue pixels per row
        row_coverage = np.sum(mask, axis=1) / (mask.shape[1] * 255.0)
        strip_rows = np.where(row_coverage >= _ROW_COVERAGE_THRESH)[0]

        if len(strip_rows) < _STRIP_MIN_HEIGHT:
            return False

        span = int(strip_rows[-1]) - int(strip_rows[0])
        if span > _STRIP_MAX_HEIGHT:
            return False

        return True

    # ------------------------------------------------------------------
    # OCR helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
        """
        Prepare a small region image for digit OCR.
        Pipeline: 4× upscale → CLAHE → Otsu threshold → dilate → padding
        """
        h, w = img_bgr.shape[:2]
        # Upscale
        img = cv2.resize(img_bgr, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        # Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # CLAHE contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        gray = clahe.apply(gray)
        # Otsu threshold
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Dilate to connect broken strokes
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        # White border padding
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
    # Fight counter: reads "X/Y" from fight_counter region
    # ------------------------------------------------------------------
    def read_fight_counter(self) -> "tuple[int, int] | None":
        """Returns (current, total) or None on failure."""
        img = self.capture_region(self._cfg["regions"]["fight_counter"])
        if img is None:
            return None
        text = self._ocr(img, _PSM7_DIGITS)
        m = re.search(r"(\d+)/(\d+)", text)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    # ------------------------------------------------------------------
    # Oslabení: reads integer from oslabeni region
    # ------------------------------------------------------------------
    def read_oslabeni(self) -> "int | None":
        """Returns oslabení value or None on failure."""
        img = self.capture_region(self._cfg["regions"]["oslabeni"])
        if img is None:
            return None
        text = self._ocr(img, _PSM7_INT)
        m = re.search(r"\d+", text)
        if m:
            return int(m.group(0))
        return None

    # ------------------------------------------------------------------
    # Button / target coordinates
    # ------------------------------------------------------------------
    def find_attack_button(self) -> "tuple[int, int]":
        """Returns absolute screen centre of the attack_button region."""
        r = self._cfg["regions"]["attack_button"]
        return (r["x"] + r["w"] // 2, r["y"] + r["h"] // 2)

    def get_click_target(self) -> "tuple[int, int]":
        """Returns absolute screen centre of the click_target region."""
        r = self._cfg["regions"]["click_target"]
        return (r["x"] + r["w"] // 2, r["y"] + r["h"] // 2)
