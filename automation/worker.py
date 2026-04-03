"""
ServerWorker — full auto mode:
  1. Scan map for blue (20%) sector badge
  2. Click it → dialog opens
  3. Check conditions (oslabení, fight counter)
  4. Fight or press Escape and scan again
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

# How long to wait after clicking a sector for the dialog to appear
_DIALOG_OPEN_WAIT  = 1.0   # seconds
# How long to wait after pressing Escape for the dialog to close
_DIALOG_CLOSE_WAIT = 0.5


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
        """Sleep for `seconds`, return False if stop was requested."""
        return not self._stop_event.wait(timeout=seconds)

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
                if not self._wait(capture_interval):
                    break
        finally:
            session.close()
            self._set(STATE_STOPPED)

    # ------------------------------------------------------------------
    # One scan cycle
    # ------------------------------------------------------------------
    def _scan_cycle(self, session: CdpSession) -> None:
        cfg         = self._server_cfg()
        max_oslabeni = cfg.get("max_oslabeni", 100)
        attack_60   = cfg.get("attack_60_percent", False)

        # --- 1. Take one screenshot and find all sector badges ---
        if not self.detector.begin_capture():
            self._set(STATE_SCANNING, sector_found=False)
            return

        badges = self.detector.find_all_sector_badges(attack_60=attack_60)
        self.detector.end_capture()

        if not badges:
            self._set(STATE_SCANNING, sector_found=False, last_error=None)
            return

        # --- 2. Try each badge until we find one worth fighting ---
        for pos in badges:
            if self._stop_event.is_set():
                return

            self._set(STATE_SCANNING, sector_found=True)
            click_once(session, *pos)

            if not self._wait(_DIALOG_OPEN_WAIT):
                return

            # Fresh screenshot to read dialog state
            if not self.detector.begin_capture():
                session.key_press("Escape")
                self.detector.end_capture()
                return

            oslabeni  = self.detector.read_oslabeni()
            counter   = self.detector.read_fight_counter()
            fight_cur = counter[0] if counter else None
            fight_tot = counter[1] if counter else None
            self.detector.end_capture()

            # Skip if over oslabení limit
            if oslabeni is not None and oslabeni >= max_oslabeni:
                session.key_press("Escape")
                self._set(STATE_SCANNING, oslabeni=oslabeni, sector_found=False)
                self._wait(_DIALOG_CLOSE_WAIT)
                continue

            # Skip if no fights left
            if counter is not None and fight_cur >= fight_tot - 3:
                session.key_press("Escape")
                self._set(STATE_SCANNING, oslabeni=oslabeni,
                          fight_current=fight_cur, fight_total=fight_tot, sector_found=False)
                self._wait(_DIALOG_CLOSE_WAIT)
                continue

            # --- Fight! ---
            self._set(STATE_FIGHTING, oslabeni=oslabeni,
                      fight_current=fight_cur, fight_total=fight_tot,
                      sector_found=True, last_error=None)

            atk_x, atk_y = self.detector.find_attack_button()
            click_once(session, atk_x, atk_y)
            if not self._wait(0.1):
                return

            tx, ty = self.detector.get_click_target()
            fast_click_loop(
                session=session, x=tx, y=ty,
                interval_ms=cfg.get("click_interval_ms", 50),
                r_every_n=cfg.get("r_key_every_n_clicks", 5),
                stop_event=self._stop_event,
                max_duration_s=30.0,
            )

            session.key_press("Escape")
            self._wait(_DIALOG_CLOSE_WAIT)
            self._set(STATE_SCANNING)
            return   # fought successfully, done for this cycle


# ---------------------------------------------------------------------------
class WorkerManager:
    def __init__(self, config: dict, socketio):
        self._config   = config
        self._socketio = socketio
        self._workers: dict[str, ServerWorker] = {}
        self._lock     = threading.Lock()

        broadcast = threading.Thread(target=self._broadcast_loop, daemon=True, name="status-broadcast")
        broadcast.start()

    def _broadcast_loop(self) -> None:
        while True:
            with self._lock:
                snapshots = [{**w.get_stats(), "server": sid}
                             for sid, w in self._workers.items()]
            for s in snapshots:
                self._socketio.emit("status_update", s)
            time.sleep(0.5)

    def start(self, server_id: str) -> None:
        with self._lock:
            existing = self._workers.get(server_id)
            if existing and existing.is_alive():
                return
            w = ServerWorker(server_id, self._config, self._socketio)
            self._workers[server_id] = w
            w.start()

    def stop(self, server_id: str) -> None:
        with self._lock:
            w = self._workers.get(server_id)
        if w:
            w.stop()

    def start_all(self) -> None:
        for sid in SERVER_IDS:
            if self._config["servers"].get(sid, {}).get("enabled"):
                self.start(sid)

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            w.stop()

    def reload_config(self, new_config: dict) -> None:
        self._config = new_config
        with self._lock:
            for w in self._workers.values():
                if w.is_alive():
                    w.update_config(new_config)
