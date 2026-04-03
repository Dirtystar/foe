"""
ServerWorker — full auto mode:
  1. Scan map for 20% sector badge
  2. Click it → dialog opens
  3. Check conditions (oslabení, fight counter)
  4. Fight or press Escape and scan again
  5. Skip list prevents re-clicking sectors with no fights for 60 s
  6. Watchdog detects stuck fight and recovers via Escape
"""
import threading
import time

from .cdp import find_tab, CdpSession
from .detector import Detector
from .clicker import click_once, fast_click_loop


SERVER_IDS = ["cz1", "cz2", "cz3", "cz4", "cz5", "cz6", "cz7", "cz8"]

STATE_STOPPED  = "stopped"
STATE_SCANNING = "scanning"
STATE_FIGHTING = "fighting"
STATE_ERROR    = "error"

_DIALOG_OPEN_WAIT  = 1.2   # s — wait for sector dialog to open
_DIALOG_CLOSE_WAIT = 0.6   # s — wait after Escape
_SKIP_RADIUS       = 35    # px — positions within this radius share a skip slot
_SKIP_TTL          = 60.0  # s — how long to skip a no-fight sector
_FIGHT_TIMEOUT     = 35.0  # s — max fight duration before watchdog kicks in


class ServerWorker(threading.Thread):
    def __init__(self, server_id: str, config: dict, socketio):
        super().__init__(daemon=True, name=f"worker-{server_id}")
        self.server_id    = server_id
        self._full_config = config
        self._socketio    = socketio
        self._stop_event  = threading.Event()
        self._lock        = threading.Lock()
        self._stats = {
            "state":         STATE_STOPPED,
            "oslabeni":      None,
            "fight_current": None,
            "fight_total":   None,
            "sector_found":  False,
            "last_error":    None,
        }
        srv_cfg  = config["servers"][server_id]
        tess_cmd = config.get("global", {}).get("tesseract_cmd", "")
        self.detector = Detector(server_id, srv_cfg, tess_cmd)

        # Sector skip list: pos_key -> expiry timestamp
        self._skip: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def stop(self) -> None:
        self._stop_event.set()

    def update_config(self, config: dict) -> None:
        self._full_config = config
        self.detector.update_config(config["servers"].get(self.server_id, {}))

    def _set(self, state: str = None, **kwargs) -> None:
        with self._lock:
            if state:
                self._stats["state"] = state
            self._stats.update(kwargs)

    def _server_cfg(self) -> dict:
        return self._full_config["servers"][self.server_id]

    def _global_cfg(self) -> dict:
        return self._full_config.get("global", {})

    def _wait(self, seconds: float) -> bool:
        return not self._stop_event.wait(timeout=seconds)

    # ------------------------------------------------------------------
    # Skip list helpers
    # ------------------------------------------------------------------
    def _skip_key(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Round position to nearest grid cell for proximity matching."""
        return (pos[0] // _SKIP_RADIUS, pos[1] // _SKIP_RADIUS)

    def _is_skipped(self, pos: tuple[int, int]) -> bool:
        key = self._skip_key(pos)
        now = time.monotonic()
        exp = self._skip.get(key, 0)
        return now < exp

    def _add_skip(self, pos: tuple[int, int]) -> None:
        self._skip[self._skip_key(pos)] = time.monotonic() + _SKIP_TTL

    def _purge_skip(self) -> None:
        now = time.monotonic()
        self._skip = {k: v for k, v in self._skip.items() if v > now}

    # ------------------------------------------------------------------
    # CDP connection
    # ------------------------------------------------------------------
    def _connect(self) -> CdpSession:
        tab_url  = self._server_cfg().get("tab_url", self.server_id)
        cdp_port = self._global_cfg().get("cdp_port", 9222)
        tab = find_tab(tab_url, cdp_port)
        if tab is None:
            raise RuntimeError(
                f"Tab '{tab_url}' not found. "
                f"Is Chrome running with --remote-debugging-port={cdp_port}?"
            )
        session = CdpSession(tab)
        session.connect()
        return session

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            session = self._connect()
        except Exception as exc:
            self._set(STATE_ERROR, last_error=str(exc))
            return

        self.detector.set_session(session)
        self._set(STATE_SCANNING, last_error=None)

        capture_interval = self._global_cfg().get("capture_interval_ms", 300) / 1000.0

        try:
            while not self._stop_event.is_set():
                try:
                    self._scan_cycle(session)
                except Exception as exc:
                    self._set(STATE_ERROR, last_error=str(exc))
                    print(f"[{self.server_id}] Error: {exc}")
                    try:
                        session.key_press("Escape")
                    except Exception:
                        pass
                if not self._wait(capture_interval):
                    break
        finally:
            session.close()
            self._set(STATE_STOPPED)

    # ------------------------------------------------------------------
    def _scan_cycle(self, session: CdpSession) -> None:
        cfg          = self._server_cfg()
        max_oslabeni = cfg.get("max_oslabeni", 100)
        attack_60    = cfg.get("attack_60_percent", False)

        self._purge_skip()

        # --- Screenshot + find badges ---
        if not self.detector.begin_capture():
            self._set(STATE_SCANNING, sector_found=False)
            return

        badges = self.detector.find_all_sector_badges(attack_60=attack_60)
        self.detector.end_capture()

        # Filter out recently skipped positions
        badges = [b for b in badges if not self._is_skipped(b)]

        if not badges:
            self._set(STATE_SCANNING, sector_found=False, last_error=None)
            return

        # --- Try each badge ---
        for pos in badges:
            if self._stop_event.is_set():
                return

            self._set(STATE_SCANNING, sector_found=True)
            click_once(session, *pos)

            if not self._wait(_DIALOG_OPEN_WAIT):
                return

            # Read dialog state
            if not self.detector.begin_capture():
                session.key_press("Escape")
                self.detector.end_capture()
                return

            oslabeni  = self.detector.read_oslabeni()
            counter   = self.detector.read_fight_counter()
            fight_cur = counter[0] if counter else None
            fight_tot = counter[1] if counter else None
            self.detector.end_capture()

            # Skip: over oslabení limit
            if oslabeni is not None and oslabeni >= max_oslabeni:
                session.key_press("Escape")
                self._add_skip(pos)
                self._set(STATE_SCANNING, oslabeni=oslabeni, sector_found=False)
                self._wait(_DIALOG_CLOSE_WAIT)
                continue

            # Skip: no fights left
            if counter is not None and fight_cur >= fight_tot - 3:
                session.key_press("Escape")
                self._add_skip(pos)
                self._set(STATE_SCANNING, oslabeni=oslabeni,
                          fight_current=fight_cur, fight_total=fight_tot,
                          sector_found=False)
                self._wait(_DIALOG_CLOSE_WAIT)
                continue

            # --- Fight ---
            self._set(STATE_FIGHTING, oslabeni=oslabeni,
                      fight_current=fight_cur, fight_total=fight_tot,
                      sector_found=True, last_error=None)

            atk_x, atk_y = self.detector.find_attack_button()
            click_once(session, atk_x, atk_y)
            if not self._wait(0.15):
                return

            tx, ty = self.detector.get_click_target()
            fast_click_loop(
                session=session, x=tx, y=ty,
                interval_ms=cfg.get("click_interval_ms", 50),
                r_every_n=cfg.get("r_key_every_n_clicks", 5),
                stop_event=self._stop_event,
                max_duration_s=_FIGHT_TIMEOUT,
            )

            # Watchdog Escape — scoped to tab via CDP
            session.key_press("Escape")
            self._wait(_DIALOG_CLOSE_WAIT)
            self._set(STATE_SCANNING)
            return   # cycle done
