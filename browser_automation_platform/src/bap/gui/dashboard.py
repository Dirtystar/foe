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


def _ms_mb(value) -> str:
    return f"{value:.0f} MB" if value is not None else "—"


def _trend_text(samples) -> str:
    if not samples:
        return "—"
    first, last = samples[0], samples[-1]
    arrow = "→"
    if last > first * 1.05:
        arrow = "↑"
    elif last < first * 0.95:
        arrow = "↓"
    return f"{arrow} {last - first:+.0f} MB"


class DashboardWidget(QWidget):
    def __init__(
        self,
        repository,
        *,
        auto_refresh_ms: int | None = None,
        max_memory_mb: int | None = None,
        max_pages: int | None = None,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._max_memory_mb = max_memory_mb
        self._max_pages = max_pages
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

        resources = QGroupBox("Browser resources")
        rgrid = QGridLayout(resources)
        self._resource_values: dict[str, QLabel] = {}
        rfields = ["Memory", "CPU", "Pages", "Contexts", "Trend", "Warning"]
        for col, name in enumerate(rfields):
            rgrid.addWidget(QLabel(name), 0, col)
            value = QLabel("—")
            value.setObjectName(f"resource_{name}")
            self._resource_values[name] = value
            rgrid.addWidget(value, 1, col)
        layout.addWidget(resources)

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
        self._render_resources()
        self._render_profiles()
        self._render_failures()

    def _render_resources(self) -> None:
        r = self._repository.browser_resources()
        v = self._resource_values
        if not r.has_data:
            for label in v.values():
                label.setText("—")
            v["Warning"].setText("no data")
            return
        v["Memory"].setText(_ms_mb(r.memory_mb))
        v["CPU"].setText(f"{r.cpu_percent:.0f}%" if r.cpu_percent is not None else "—")
        v["Pages"].setText(str(r.pages))
        v["Contexts"].setText(str(r.contexts))
        v["Trend"].setText(_trend_text(r.memory_trend))
        warnings = []
        if self._max_memory_mb and r.memory_mb is not None and r.memory_mb > self._max_memory_mb:
            warnings.append("memory")
        if self._max_pages and r.pages > self._max_pages:
            warnings.append("pages")
        v["Warning"].setText("⚠ " + ", ".join(warnings) if warnings else "ok")

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
