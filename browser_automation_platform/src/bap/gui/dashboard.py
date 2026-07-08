"""Analytics dashboard panel.

A pure view over a MetricsRepository, injected at construction — the widget
never touches SQLite and holds no analytics logic; it only formats what the
repository returns. Refresh is manual (button) or timer-based; there is no
live event subscription here.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QTimer

_PROFILE_COLS = ["Profile", "Health", "Ticks/min", "Errors", "Action success"]
_FAILURE_COLS = ["Timestamp", "Profile", "Reason"]


def _ms(value) -> str:
    return f"{value:.0f} ms" if value is not None else "—"


def _pct(value) -> str:
    return f"{value * 100:.0f}%" if value is not None else "—"


class DashboardWidget(QWidget):
    def __init__(self, repository, *, auto_refresh_ms: int | None = None) -> None:
        super().__init__()
        self._repository = repository
        self._build_ui()
        self.refresh()
        if auto_refresh_ms:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.refresh)
            self._timer.start(auto_refresh_ms)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        overview = QGroupBox("Overview")
        grid = QGridLayout(overview)
        self._overview_values: dict[str, QLabel] = {}
        fields = ["Total ticks", "Success", "Avg latency", "p95 latency", "Recoveries"]
        for col, name in enumerate(fields):
            grid.addWidget(QLabel(name), 0, col)
            value = QLabel("—")
            value.setObjectName(f"metric_{name}")
            self._overview_values[name] = value
            grid.addWidget(value, 1, col)
        layout.addWidget(overview)

        self.profile_table = QTableWidget(0, len(_PROFILE_COLS))
        self.profile_table.setHorizontalHeaderLabels(_PROFILE_COLS)
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.profile_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(QLabel("Per profile"))
        layout.addWidget(self.profile_table, stretch=1)

        self.failure_table = QTableWidget(0, len(_FAILURE_COLS))
        self.failure_table.setHorizontalHeaderLabels(_FAILURE_COLS)
        self.failure_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.failure_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(QLabel("Recent failures"))
        layout.addWidget(self.failure_table, stretch=1)

        controls = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addStretch(1)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

    def refresh(self) -> None:
        self._render_overview()
        self._render_profiles()
        self._render_failures()

    def _render_overview(self) -> None:
        s = self._repository.overview()
        self._overview_values["Total ticks"].setText(str(s.total_ticks))
        self._overview_values["Success"].setText(_pct(s.success_rate))
        self._overview_values["Avg latency"].setText(_ms(s.avg_duration_ms))
        self._overview_values["p95 latency"].setText(_ms(s.p95_duration_ms))
        self._overview_values["Recoveries"].setText(str(s.recovery_count))

    def _render_profiles(self) -> None:
        profiles = self._repository.per_profile()
        self.profile_table.setRowCount(len(profiles))
        for row, p in enumerate(profiles):
            cells = [
                p.profile_id,
                p.health,
                f"{p.ticks_per_min:.1f}",
                str(p.failures),
                _pct(p.action_success_rate),
            ]
            for col, text in enumerate(cells):
                self.profile_table.setItem(row, col, QTableWidgetItem(text))

    def _render_failures(self) -> None:
        failures = self._repository.recent_failures()
        self.failure_table.setRowCount(len(failures))
        for row, f in enumerate(failures):
            ts = f.timestamp.strftime("%H:%M:%S") if f.timestamp else "—"
            for col, text in enumerate([ts, f.profile_id, f.reason]):
                self.failure_table.setItem(row, col, QTableWidgetItem(text))


__all__ = ["DashboardWidget"]
