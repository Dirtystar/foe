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


# 20% sector badge — WHITE pentagon (low saturation, very bright)
_WHITE_LOWER  = np.array([0,   0,  210], dtype=np.uint8)
_WHITE_UPPER  = np.array([180, 45, 255], dtype=np.uint8)

# 60% sector badge — RED (dark red pentagon)
_RED_LOWER1   = np.array([0,   140, 120], dtype=np.uint8)
_RED_UPPER1   = np.array([8,   255, 255], dtype=np.uint8)
_RED_LOWER2   = np.array([172, 140, 120], dtype=np.uint8)
_RED_UPPER2   = np.array([180, 255, 255], dtype=np.uint8)

_MIN_BADGE_AREA =  300   # px²
_MAX_BADGE_AREA = 4000   # px²

_PSM7_DIGITS = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/"
_PSM7_INT    = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"


def _png_to_bgr(png_bytes: bytes) -> "np.ndarray | None":
    if not _PIL_OK or not _CV2_OK:
        return None
    try:
        img = _PILImage.open(BytesIO(png_bytes)).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        return arr[:, :, ::-1]
    except Exception:
        return None


class Detector:
    def __init__(self, server_id: str, server_config: dict, tesseract_cmd: str = ""):
        self.server_id   = server_id
        self._cfg        = server_config
        self._tess_cmd   = tesseract_cmd
        self._session    = None
        self._frame: "np.ndarray | None" = None   # cached screenshot for current cycle

    def set_session(self, session) -> None:
        self._session = session

    def update_config(self, server_config: dict) -> None:
        self._cfg = server_config

    # ------------------------------------------------------------------
    # Screenshot cache — call begin_capture() once per scan cycle
    # ------------------------------------------------------------------
    def begin_capture(self) -> bool:
        """Take a fresh screenshot and cache it. Returns False on failure."""
        if self._session is None:
            return False
        png = self._session.screenshot_png()
        if png is None:
            return False
        self._frame = _png_to_bgr(png)
        return self._frame is not None

    def end_capture(self) -> None:
        self._frame = None

    def capture_full_window(self) -> "np.ndarray | None":
        """For calibration screenshot — always fresh."""
        if self._session is None:
            return None
        png = self._session.screenshot_png()
        return _png_to_bgr(png) if png else None

    # ------------------------------------------------------------------
    # Region crop from cached frame
    # ------------------------------------------------------------------
    def _crop(self, region: dict) -> "np.ndarray | None":
        if self._frame is None:
            return None
        x, y = int(region["x"]), int(region["y"])
        w, h = int(region.get("w", 0)), int(region.get("h", 0))
        if w <= 0 or h <= 0:
            return None
        img_h, img_w = self._frame.shape[:2]
        x2 = min(x + w, img_w)
        y2 = min(y + h, img_h)
        if x2 <= x or y2 <= y:
            return None
        return self._frame[y:y2, x:x2]

    def capture_region(self, region: dict) -> "np.ndarray | None":
        return self._crop(region)

    # ------------------------------------------------------------------
    # Find all 20% (blue) sector badges on the map
    # Returns list of (x, y) in VIEWPORT pixel coords, sorted by area desc
    # ------------------------------------------------------------------
    def find_all_sector_badges(self, attack_60: bool = False) -> "list[tuple[int, int]]":
        img = self._crop(self._cfg["regions"]["sector_list"])
        if img is None:
            return []

        hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # 20% badge = white pentagon
        mask = cv2.inRange(hsv, _WHITE_LOWER, _WHITE_UPPER)
        if attack_60:
            # 60% badge = red pentagon
            red = cv2.bitwise_or(
                cv2.inRange(hsv, _RED_LOWER1, _RED_UPPER1),
                cv2.inRange(hsv, _RED_LOWER2, _RED_UPPER2),
            )
            mask = cv2.bitwise_or(mask, red)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        region = self._cfg["regions"]["sector_list"]
        results = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < _MIN_BADGE_AREA or area > _MAX_BADGE_AREA:
                continue

            # Aspect ratio filter: badge is wider than tall (ratio 1.3 – 5.0)
            x, y, w, h = cv2.boundingRect(cnt)
            if h == 0:
                continue
            ratio = w / h
            if ratio < 1.3 or ratio > 5.0:
                continue

            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            lx = int(M["m10"] / M["m00"])
            ly = int(M["m01"] / M["m00"])

            results.append((area, region["x"] + lx, region["y"] + ly))

        results.sort(key=lambda r: r[0], reverse=True)
        print(f"[{self.server_id}] badges found: {[(x,y) for _,x,y in results]}")
        return [(x, y) for _, x, y in results]

    def find_sector_badge(self, attack_60: bool = False) -> "tuple[int, int] | None":
        badges = self.find_all_sector_badges(attack_60)
        return badges[0] if badges else None

    # ------------------------------------------------------------------
    # OCR helpers
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
        img = self._crop(self._cfg["regions"]["fight_counter"])
        if img is None:
            return None
        m = re.search(r"(\d+)/(\d+)", self._ocr(img, _PSM7_DIGITS))
        return (int(m.group(1)), int(m.group(2))) if m else None

    def read_oslabeni(self) -> "int | None":
        img = self._crop(self._cfg["regions"]["oslabeni"])
        if img is None:
            return None
        m = re.search(r"\d+", self._ocr(img, _PSM7_INT))
        return int(m.group(0)) if m else None

    # ------------------------------------------------------------------
    # Click targets — in screenshot-pixel (viewport) coordinates
    # ------------------------------------------------------------------
    def find_attack_button(self) -> tuple[int, int]:
        r = self._cfg["regions"]["attack_button"]
        return (int(r["x"]) + int(r["w"]) // 2, int(r["y"]) + int(r["h"]) // 2)

    def get_click_target(self) -> tuple[int, int]:
        r = self._cfg["regions"]["click_target"]
        return (int(r["x"]) + int(r["w"]) // 2, int(r["y"]) + int(r["h"]) // 2)
