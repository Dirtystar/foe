import sys
import os
import json
import socket as sock
import tempfile
import base64

from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATIC_DIR  = os.path.join(BASE_DIR, "static")

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------
SERVER_IDS = ["cz1", "cz2", "cz3", "cz4", "cz5", "cz6", "cz7", "cz8"]
DEFAULT_MAX_OSLABENI = {"cz8": 156}

DEFAULT_SERVER = {
    "enabled": False,
    "max_oslabeni": 100,
    "window_title": "",          # search string to find the browser window
    "regions": {
        "sector_list":   {"x": 0, "y": 0, "w": 0, "h": 0},
        "fight_counter": {"x": 0, "y": 0, "w": 0, "h": 0},
        "oslabeni":      {"x": 0, "y": 0, "w": 0, "h": 0},
        "attack_button": {"x": 0, "y": 0, "w": 0, "h": 0},
        "click_target":  {"x": 0, "y": 0, "w": 1, "h": 1},
    },
    "click_interval_ms": 50,
    "r_key_every_n_clicks": 5,
}

DEFAULT_GLOBAL = {
    "capture_interval_ms": 300,
    "tesseract_cmd": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
}


def create_default_config() -> dict:
    servers = {}
    for sid in SERVER_IDS:
        srv = json.loads(json.dumps(DEFAULT_SERVER))
        srv["max_oslabeni"] = DEFAULT_MAX_OSLABENI.get(sid, 100)
        srv["window_title"] = sid   # default: search by server id e.g. "cz1"
        servers[sid] = srv
    return {"servers": servers, "global": dict(DEFAULT_GLOBAL)}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    default = create_default_config()
    if not os.path.exists(CONFIG_PATH):
        return default
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return _deep_merge(default, saved)
    except Exception as e:
        print(f"WARNING: Could not load config.json: {e}. Using defaults.")
        return default


def save_config(config: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=BASE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Port check
# ---------------------------------------------------------------------------
def check_port(port: int) -> bool:
    with sock.socket(sock.AF_INET, sock.SOCK_STREAM) as s:
        try:
            s.setsockopt(sock.SOL_SOCKET, sock.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Tesseract check
# ---------------------------------------------------------------------------
def check_tesseract(cmd: str) -> None:
    try:
        import pytesseract
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        ver   = pytesseract.get_tesseract_version()
        langs = pytesseract.get_languages(config="")
        if "ces" not in langs:
            print(
                "WARNING: Czech (ces) Tesseract language pack not found.\n"
                "Download ces.traineddata and place it in your Tesseract tessdata directory."
            )
        else:
            print(f"Tesseract {ver} OK, Czech pack present.")
    except Exception as e:
        print(f"WARNING: Tesseract not available: {e}\nOCR detection will not work.")


# ---------------------------------------------------------------------------
# Flask + SocketIO app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=STATIC_DIR)
app.config["SECRET_KEY"] = "foe-automation-secret"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

manager      = None
config_state: dict = {}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------
@socketio.on("connect")
def on_connect():
    emit("full_config", config_state)


@socketio.on("start_server")
def on_start_server(data):
    sid = data.get("server")
    if sid and manager:
        manager.start(sid)


@socketio.on("stop_server")
def on_stop_server(data):
    sid = data.get("server")
    if sid and manager:
        manager.stop(sid)


@socketio.on("start_all")
def on_start_all(_data):
    if manager:
        manager.start_all()


@socketio.on("stop_all")
def on_stop_all(_data):
    if manager:
        manager.stop_all()


@socketio.on("save_config")
def on_save_config(data):
    sid = data.get("server")
    if not sid or sid not in SERVER_IDS:
        emit("error", {"message": f"Unknown server: {sid}", "fatal": False})
        return
    try:
        config_state["servers"][sid]["enabled"]            = bool(data.get("enabled", False))
        config_state["servers"][sid]["max_oslabeni"]       = int(data.get("max_oslabeni", 100))
        config_state["servers"][sid]["click_interval_ms"]  = int(data.get("click_interval_ms", 50))
        config_state["servers"][sid]["r_key_every_n_clicks"] = int(data.get("r_key_every_n_clicks", 5))
        save_config(config_state)
        if manager:
            manager.reload_config(config_state)
        emit("config_saved", {"ok": True, "server": sid})
    except Exception as e:
        emit("error", {"message": str(e), "fatal": False})


@socketio.on("save_window_title")
def on_save_window_title(data):
    """data = {server: "cz1", window_title: "Forge of Empires"}"""
    sid = data.get("server")
    if not sid or sid not in SERVER_IDS:
        return
    try:
        config_state["servers"][sid]["window_title"] = str(data.get("window_title", "")).strip()
        save_config(config_state)
        if manager:
            manager.reload_config(config_state)
        emit("config_saved", {"ok": True, "server": sid})
    except Exception as e:
        emit("error", {"message": str(e), "fatal": False})


@socketio.on("list_windows")
def on_list_windows(data):
    """Return all visible windows whose title matches the search string."""
    search = data.get("search", "")
    try:
        from automation.capture import list_windows
        windows = list_windows(search)
        emit("windows_list", {"windows": windows})
    except Exception as e:
        emit("windows_list", {"windows": [], "error": str(e)})


@socketio.on("save_regions")
def on_save_regions(data):
    """
    Regions are now in window client-area coordinates (relative to top-left of the window).
    data = {server, regions: {key: {x,y,w,h}, ...}}
    """
    sid = data.get("server")
    if not sid or sid not in SERVER_IDS:
        emit("error", {"message": f"Unknown server: {sid}", "fatal": False})
        return
    try:
        REGION_KEYS = ["sector_list", "fight_counter", "oslabeni", "attack_button", "click_target"]
        regions = data.get("regions", {})
        for key in REGION_KEYS:
            if key in regions:
                r = regions[key]
                config_state["servers"][sid]["regions"][key] = {
                    "x": int(r.get("x", 0)),
                    "y": int(r.get("y", 0)),
                    "w": int(r.get("w", 0)),
                    "h": int(r.get("h", 0)),
                }
        save_config(config_state)
        if manager:
            manager.reload_config(config_state)
        emit("config_saved", {"ok": True, "server": sid})
    except Exception as e:
        emit("error", {"message": str(e), "fatal": False})


@socketio.on("request_screenshot")
def on_request_screenshot(data):
    """Capture the game window using PrintWindow (works in background)."""
    sid = data.get("server")
    if not sid or sid not in SERVER_IDS:
        return
    try:
        from automation.capture import find_window, capture_window
        import numpy as np
        from PIL import Image
        import io

        window_title = config_state["servers"][sid].get("window_title", "")
        if not window_title:
            emit("error", {"message": "Nastav název okna a ulož ho před pořízením screenshotu.", "fatal": False})
            return

        hwnd = find_window(window_title)
        if hwnd is None:
            emit("error", {"message": f"Okno '{window_title}' nenalezeno. Zkontroluj název.", "fatal": False})
            return

        img_bgr = capture_window(hwnd)
        if img_bgr is None:
            emit("error", {"message": "Zachycení okna selhalo.", "fatal": False})
            return

        img_rgb = img_bgr[:, :, ::-1]
        pil_img = Image.fromarray(img_rgb)

        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        emit("calibration_screenshot", {
            "server":    sid,
            "image_b64": b64,
            "width":     pil_img.width,
            "height":    pil_img.height,
        })
    except Exception as e:
        emit("error", {"message": f"Screenshot selhal: {e}", "fatal": False})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    PORT = 9000

    if not check_port(PORT):
        print(f"ERROR: Port {PORT} is already in use.")
        sys.exit(1)

    config_state = load_config()
    save_config(config_state)

    tess_cmd = config_state.get("global", {}).get("tesseract_cmd", "")
    check_tesseract(tess_cmd)

    from automation.worker import WorkerManager
    manager = WorkerManager(config_state, socketio)

    print(f"FoE Battle Automation running at http://localhost:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)
