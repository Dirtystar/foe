"""
ServerWorker thread and WorkerManager for FoE Guild Battle automation.

Each ServerWorker:
  - Runs in its own daemon thread
  - Owns a Detector instance (and thus its own mss context)
  - Scans for sectors → clicks → reports status back via SocketIO
"""
import threading
import time

from .detector import Detector
from .clicker import click_once, fast_click_loop


SERVER_IDS = ["cz1", "cz2", "cz3", "cz4", "cz5", "cz6", "cz7", "cz8"]

# States
STATE_STOPPED   = "stopped"
STATE_SCANNING  = "scanning"
STATE_FIGHTING  = "fighting"
STATE_ERROR     = "error"


class ServerWorker(threading.Thread):
    def __init__(self, server_id: str, config: dict, socketio):
        super().__init__(daemon=True, name=f"worker-{server_id}")
        self.server_id = server_id
        self._full_config = config
        self._socketio = socketio

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._stats = {
            "state":         STATE_STOPPED,
            "oslabeni":      None,
            "fight_current": None,
            "fight_total":   None,
            "sector_found":  False,
            "last_error":    None,
        }

        srv_cfg = config["servers"][server_id]
        tess_cmd = config.get("global", {}).get("tesseract_cmd", "")
        self.detector = Detector(server_id, srv_cfg, tess_cmd)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def stop(self) -> None:
        self._stop_event.set()

    def update_config(self, config: dict) -> None:
        """Hot-reload config (picked up on next scan cycle)."""
        self._full_config = config
        srv_cfg = config["servers"].get(self.server_id, {})
        self.detector.update_config(srv_cfg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _set(self, state: str = None, **kwargs) -> None:
        with self._lock:
            if state:
                self._stats["state"] = state
            self._stats.update(kwargs)

    def _server_cfg(self) -> dict:
        return self._full_config["servers"][self.server_id]

    def _global_cfg(self) -> dict:
        return self._full_config.get("global", {})

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._set(STATE_SCANNING)
        capture_interval = self._global_cfg().get("capture_interval_ms", 300) / 1000.0

        while not self._stop_event.is_set():
            try:
                self._scan_cycle()
            except Exception as exc:
                self._set(STATE_ERROR, last_error=str(exc))
                print(f"[{self.server_id}] Unhandled error: {exc}")
            # Sleep between scan cycles, but wake immediately on stop
            self._stop_event.wait(timeout=capture_interval)

        self._set(STATE_STOPPED)

    def _scan_cycle(self) -> None:
        cfg = self._server_cfg()
        max_oslabeni = cfg.get("max_oslabeni", 100)

        # --- 1. Check oslabení ---
        oslabeni = self.detector.read_oslabeni()
        if oslabeni is not None and oslabeni >= max_oslabeni:
            self._set(STATE_SCANNING,
                      oslabeni=oslabeni, sector_found=False, last_error=None)
            return

        # --- 2. Check fight counter ---
        counter = self.detector.read_fight_counter()
        fight_cur = counter[0] if counter else None
        fight_tot = counter[1] if counter else None
        if counter is not None and fight_cur >= fight_tot - 3:
            self._set(STATE_SCANNING,
                      oslabeni=oslabeni,
                      fight_current=fight_cur,
                      fight_total=fight_tot,
                      sector_found=False,
                      last_error=None)
            return

        # --- 3. Detect blue strip ---
        strip_found = self.detector.detect_blue_strip()
        if not strip_found:
            self._set(STATE_SCANNING,
                      oslabeni=oslabeni,
                      fight_current=fight_cur,
                      fight_total=fight_tot,
                      sector_found=False,
                      last_error=None)
            return

        # --- 4. All conditions met → fight ---
        self._set(STATE_FIGHTING,
                  oslabeni=oslabeni,
                  fight_current=fight_cur,
                  fight_total=fight_tot,
                  sector_found=True,
                  last_error=None)

        atk_x, atk_y = self.detector.find_attack_button()
        click_once(atk_x, atk_y)
        # Brief settle for game UI to respond
        time.sleep(0.05)

        tx, ty = self.detector.get_click_target()
        fast_click_loop(
            x=tx,
            y=ty,
            interval_ms=cfg.get("click_interval_ms", 50),
            r_every_n=cfg.get("r_key_every_n_clicks", 5),
            stop_event=self._stop_event,
            max_duration_s=30.0,
        )

        self._set(STATE_SCANNING)


# ---------------------------------------------------------------------------
# WorkerManager
# ---------------------------------------------------------------------------
class WorkerManager:
    def __init__(self, config: dict, socketio):
        self._config = config
        self._socketio = socketio
        self._workers: dict[str, ServerWorker] = {}
        self._lock = threading.Lock()

        # Status broadcast thread
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop,
            daemon=True,
            name="status-broadcast",
        )
        self._broadcast_thread.start()

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------
    def _broadcast_loop(self) -> None:
        while True:
            snapshots = []
            with self._lock:
                for sid, w in self._workers.items():
                    stats = w.get_stats()
                    stats["server"] = sid
                    snapshots.append(stats)

            # Emit all updates; SocketIO handles thread-safety internally
            for stats in snapshots:
                self._socketio.emit("status_update", stats)

            time.sleep(0.5)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
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
        """Push updated config to all workers (running or not)."""
        self._config = new_config
        with self._lock:
            for sid, w in self._workers.items():
                if w.is_alive():
                    w.update_config(new_config)
