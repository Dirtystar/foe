"""Forge GBG Farmer — the end-user desktop app.

A deliberately small window: paste a licence key, tick the worlds to farm, set each world's
attrition limit and which weakening %s to attack, press **Start**. The app owns its browser (via
the launcher) and drives Guild Battlegrounds across the enabled worlds until you press **Stop**.

    python -m bap.forge.app.farmer_gui

The number of worlds you may enable is capped by your licence tier (see ``bap.forge.licensing``);
with no key you get the free tier (1 world).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.forge import licensing

WORLDS = ["cz1", "cz2", "cz3", "cz4", "cz5", "cz6", "cz7", "cz8"]
PCTS = [20, 40, 60, 80, 100]
LICENSE_FILE = "license.key"
EMAIL_FILE = "license.email"
CONFIG_FILE = "worlds_farm.json"
ACCEPT_FILE = os.path.join(os.path.expanduser("~"), ".forge_gbg_farmer_accepted")

FOOTER_DISCLAIMER = (
    "Independent, unofficial tool — not affiliated with or endorsed by InnoGames or Forge of "
    "Empires. Use at your own risk; automation may breach the game's Terms and get your account "
    "banned. Provided “as is”, no warranty, no liability.")

DISCLAIMER_TEXT = (
    "Forge GBG Farmer is an independent, unofficial tool. It is NOT affiliated with, endorsed "
    "by, or associated with InnoGames or Forge of Empires; all trademarks belong to their "
    "owners.\n\n"
    "USE AT YOUR OWN RISK. Automating gameplay may violate the game's Terms of Service and can "
    "result in warnings, suspension, or a permanent ban of your game account. You are solely "
    "responsible for how you use this app and for any consequences, including account penalties "
    "or loss of in-game items or progress.\n\n"
    "The app is provided “as is”, without warranty of any kind. To the maximum extent "
    "permitted by law, the authors and distributors accept no liability for any damages or "
    "account actions arising from its use.\n\n"
    "By clicking “I understand and accept” you agree to these terms.")


def _read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _load_license_key() -> str:
    return os.environ.get("FOE_LICENSE_KEY") or _read_file(LICENSE_FILE)


class WorldRow:
    """The widgets for one world's row in the table."""

    def __init__(self, world: str):
        self.world = world
        self.enable = QCheckBox()
        self.tab = QLineEdit(world)
        self.limit = QSpinBox()
        self.limit.setRange(0, 2000)
        self.limit.setValue(150)
        self.pcts = {p: QCheckBox(f"{p}") for p in PCTS}
        for p in (20, 40, 60):
            self.pcts[p].setChecked(True)

    def config(self) -> dict:
        chosen = [p for p in PCTS if self.pcts[p].isChecked()]
        return {"world": self.world, "tab": self.tab.text().strip() or self.world,
                "limit": self.limit.value(), "pcts": chosen}


class FarmerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Forge GBG Farmer")
        self.setMinimumWidth(760)
        self._proc: subprocess.Popen | None = None
        self.rows: list[WorldRow] = []

        root = QVBoxLayout(self)

        # --- licence -------------------------------------------------------
        lic_box = QGridLayout()
        lic_box.addWidget(QLabel("Licence key:"), 0, 0)
        self.key_edit = QLineEdit(_load_license_key())
        self.key_edit.setPlaceholderText("FOE-…  (leave empty for the free tier: 1 world)")
        lic_box.addWidget(self.key_edit, 0, 1)
        self.save_key_btn = QPushButton("Save")
        self.save_key_btn.clicked.connect(self._save_key)
        lic_box.addWidget(self.save_key_btn, 0, 2)
        lic_box.addWidget(QLabel("Purchase email:"), 1, 0)
        self.email_edit = QLineEdit(_read_file(EMAIL_FILE))
        self.email_edit.setPlaceholderText("the email you bought with (for online verification)")
        lic_box.addWidget(self.email_edit, 1, 1)
        self.check_btn = QPushButton("Check online")
        self.check_btn.clicked.connect(self._check_online)
        lic_box.addWidget(self.check_btn, 1, 2)
        self.lic_label = QLabel()
        self.lic_label.setWordWrap(True)
        lic_box.addWidget(self.lic_label, 2, 0, 1, 3)
        root.addLayout(lic_box)

        # --- worlds table --------------------------------------------------
        cols = ["Farm", "World", "Browser tab", "Attrition limit"] + [f"{p}%" for p in PCTS]
        self.table = QTableWidget(len(WORLDS), len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, w in enumerate(WORLDS):
            row = WorldRow(w)
            self.rows.append(row)
            self.table.setCellWidget(i, 0, _centre(row.enable))
            self.table.setItem(i, 1, _readonly(w))
            self.table.setCellWidget(i, 2, row.tab)
            self.table.setCellWidget(i, 3, row.limit)
            for j, p in enumerate(PCTS):
                self.table.setCellWidget(i, 4 + j, _centre(row.pcts[p]))
            row.enable.stateChanged.connect(self._refresh_license)
        self.table.resizeColumnsToContents()
        root.addWidget(self.table)

        # --- actions -------------------------------------------------------
        btns = QHBoxLayout()
        self.status = QLabel("Idle.")
        btns.addWidget(self.status, 1)
        self.launch_btn = QPushButton("Open browser")
        self.launch_btn.clicked.connect(self._launch_browser)
        btns.addWidget(self.launch_btn)
        self.start_btn = QPushButton("Start farming")
        self.start_btn.clicked.connect(self._start)
        btns.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btns.addWidget(self.stop_btn)
        root.addLayout(btns)

        # Always-visible liability notice.
        disc = QLabel(FOOTER_DISCLAIMER)
        disc.setWordWrap(True)
        disc.setStyleSheet("color:#888;font-size:11px;")
        root.addWidget(disc)

        self.key_edit.textChanged.connect(self._refresh_license)

        # Poll the farm subprocess so the UI resets itself when farming ends on its own.
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._poll_proc)
        self._timer.start()
        self._refresh_license()

    def _plan_line(self, lic) -> str:
        """Tier + price, plus a one-line upsell to the next tier up."""
        tiers = list(licensing.TIERS.values())
        cur = licensing.TIERS.get(lic.tier) if lic and lic.is_valid() else None
        if cur is None:
            nxt = tiers[0]
            return f"Free tier (1 world). Upgrade to {nxt.name} for {nxt.price_label}."
        higher = [t for t in tiers if t.price_usd > cur.price_usd]
        up = f"  Upgrade to {higher[0].name} for {higher[0].price_label}." if higher else ""
        worlds = "unlimited" if cur.worlds is None else f"{cur.worlds}"
        return f"{cur.name} plan — {worlds} worlds, {cur.price_label}.{up}"

    def _poll_proc(self):
        if self._proc is not None and self._proc.poll() is not None:
            self._proc = None
            self.status.setText("Farming stopped.")
            self.stop_btn.setEnabled(False)
            self._refresh_license()

    # -- licence ------------------------------------------------------------
    def _current_key(self) -> str:
        return self.key_edit.text().strip()

    def _allowed(self) -> int:
        return licensing.allowed_worlds(self._current_key() or None)

    def _refresh_license(self, *_):
        key = self._current_key()
        lic = licensing.verify_key(key) if key else None
        allowed = self._allowed()
        self.lic_label.setText(f"{licensing.describe(lic)}  →  up to {allowed} world(s).\n"
                               f"{self._plan_line(lic)}")
        enabled = [r for r in self.rows if r.enable.isChecked()]
        over = len(enabled) > allowed
        self.status.setText(
            f"{len(enabled)} world(s) selected, plan allows {allowed}."
            + ("  Too many — untick some." if over else ""))
        self.start_btn.setEnabled(not over and len(enabled) > 0 and self._proc is None)

    def _save_key(self):
        try:
            with open(LICENSE_FILE, "w", encoding="utf-8") as fh:
                fh.write(self._current_key())
            with open(EMAIL_FILE, "w", encoding="utf-8") as fh:
                fh.write(self.email_edit.text().strip())
            self.status.setText(f"Licence saved to {LICENSE_FILE}.")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _check_online(self):
        """One-shot online verification (revocation + email). Authoritative check also runs at
        Start; this just shows the result now."""
        from bap.forge import license_online
        key = self._current_key()
        if not key:
            self.status.setText("Enter a licence key first.")
            return
        self.status.setText("Checking licence online…")
        QApplication.processEvents()
        worlds, note = license_online.entitlement(key, self.email_edit.text().strip() or None)
        self.lic_label.setText(note + f"  →  up to {worlds} world(s).")
        self.status.setText("Licence checked.")

    # -- run ----------------------------------------------------------------
    def _enabled_configs(self) -> list[dict]:
        return [r.config() for r in self.rows if r.enable.isChecked()]

    def _launch_browser(self):
        try:
            subprocess.Popen([sys.executable, "-m", "bap.forge.action.launcher"])  # noqa: S603
            self.status.setText("Browser launching — log in to your worlds, then Start.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Launch failed", str(exc))

    def _start(self):
        if self._proc is not None:
            return
        worlds = self._enabled_configs()
        if not worlds:
            return
        if len(worlds) > self._allowed():
            QMessageBox.warning(self, "Licence limit",
                                "You selected more worlds than your plan allows.")
            return
        cfg = {"gbg": {"x": 1390, "y": 250}, "worlds": worlds}
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        cmd = [sys.executable, "-m", "bap.forge.action.open_targets",
               "--worlds", CONFIG_FILE]
        if self._current_key():
            cmd += ["--license", self._current_key()]
        if self.email_edit.text().strip():
            cmd += ["--email", self.email_edit.text().strip()]
        try:
            self._proc = subprocess.Popen(cmd)  # noqa: S603
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Start failed", str(exc))
            return
        self.status.setText(f"Farming {len(worlds)} world(s)… (PID {self._proc.pid})")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None
        self.status.setText("Stopped.")
        self.stop_btn.setEnabled(False)
        self._refresh_license()


def _centre(widget: QWidget) -> QWidget:
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignCenter)
    lay.addWidget(widget)
    return holder


def _readonly(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsEnabled)
    return it


def _require_acceptance() -> bool:  # pragma: no cover - GUI
    """Show the disclaimer once; the user must accept before using the app. Returns True to
    proceed. Acceptance is recorded so it's asked only on the first run."""
    if os.path.exists(ACCEPT_FILE):
        return True
    box = QMessageBox()
    box.setWindowTitle("Before you start — please read")
    box.setIcon(QMessageBox.Warning)
    box.setText("Disclaimer & Terms of Use")
    box.setInformativeText(DISCLAIMER_TEXT)
    accept = box.addButton("I understand and accept", QMessageBox.AcceptRole)
    box.addButton("Quit", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is accept:
        try:
            with open(ACCEPT_FILE, "w", encoding="utf-8") as fh:
                fh.write("accepted\n")
        except OSError:
            pass
        return True
    return False


def main(argv=None) -> int:  # pragma: no cover - GUI
    app = QApplication.instance() or QApplication(argv or sys.argv)
    if not _require_acceptance():
        return 0
    win = FarmerWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
