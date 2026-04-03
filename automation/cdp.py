"""
Chrome DevTools Protocol (CDP) client.

Allows taking screenshots and injecting mouse/keyboard events into specific
browser tabs identified by URL — works even when the tab is in the background.

Requires Chrome/Edge launched with:
    --remote-debugging-port=9222
"""
import base64
import json
import threading

import requests
import websocket   # websocket-client


# ---------------------------------------------------------------------------
# Tab discovery
# ---------------------------------------------------------------------------

def list_tabs(cdp_port: int = 9222) -> list[dict]:
    """Return all open tabs from the CDP JSON endpoint."""
    try:
        # Use 127.0.0.1 explicitly — on Windows 'localhost' may resolve to ::1
        resp = requests.get(f"http://127.0.0.1:{cdp_port}/json", timeout=3)
        tabs = [t for t in resp.json() if t.get("type") == "page"]
        print(f"CDP list_tabs: found {len(tabs)} tabs on port {cdp_port}")
        return tabs
    except Exception as e:
        print(f"CDP list_tabs error: {e}")
        return []


def find_tab(url_fragment: str, cdp_port: int = 9222) -> dict | None:
    """Find the first tab whose URL contains url_fragment (case-insensitive)."""
    tabs = list_tabs(cdp_port)
    for tab in tabs:
        if url_fragment.lower() in tab.get("url", "").lower():
            return tab
    print(f"CDP find_tab: no tab matching '{url_fragment}' among {[t.get('url') for t in tabs]}")
    return None


# ---------------------------------------------------------------------------
# CDP session (persistent WebSocket connection to one tab)
# ---------------------------------------------------------------------------

class CdpSession:
    """
    Manages a persistent WebSocket connection to a single browser tab.
    Thread-safe — multiple workers can each hold their own session.
    """

    def __init__(self, tab_info: dict):
        self.tab_id  = tab_info.get("id", "")
        self.url     = tab_info.get("url", "")
        self._ws_url = tab_info["webSocketDebuggerUrl"]
        self._ws     = None
        self._lock   = threading.Lock()
        self._cmd_id = 0
        self.dpr     = 1.0   # device pixel ratio (set on connect)

    # ------------------------------------------------------------------
    def connect(self) -> None:
        self._ws = websocket.WebSocket()
        self._ws.connect(self._ws_url, origin="http://localhost")
        self._send("Page.enable")
        result = self._send("Runtime.evaluate", {"expression": "window.devicePixelRatio"})
        self.dpr = float(result.get("result", {}).get("value", 1.0) or 1.0)

    def close(self) -> None:
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def is_connected(self) -> bool:
        return self._ws is not None

    # ------------------------------------------------------------------
    def _send(self, method: str, params: dict = None) -> dict:
        with self._lock:
            self._cmd_id += 1
            cid = self._cmd_id
            self._ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(self._ws.recv())
                if msg.get("id") == cid:
                    return msg.get("result", {})

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------
    def screenshot_png(self) -> bytes | None:
        """Capture the tab viewport as PNG bytes."""
        try:
            result = self._send("Page.captureScreenshot", {
                "format":      "png",
                "fromSurface": False,   # rendered pixels, not compositor surface
            })
            data = result.get("data")
            return base64.b64decode(data) if data else None
        except Exception as e:
            print(f"CDP screenshot error: {e}")
            return None

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def click(self, x: int, y: int) -> None:
        """
        Click at (x, y) in screenshot-pixel coordinates.
        Converts to CSS pixels using device pixel ratio.
        Works even when the tab is in the background.
        """
        cx = x / self.dpr
        cy = y / self.dpr
        for event_type in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type":        event_type,
                "x":           cx,
                "y":           cy,
                "button":      "left",
                "buttons":     1,
                "clickCount":  1,
                "pointerType": "mouse",
            })

    def key_press(self, key: str) -> None:
        """Press and release a key (e.g. 'r', 'Enter')."""
        for event_type in ("keyDown", "keyUp"):
            self._send("Input.dispatchKeyEvent", {"type": event_type, "key": key})
