"""Performance dashboard page (Milestone 4.9 — measurement only).

Reads snapshots from a `bap.perf.registry.MetricsRegistry` and presents per-World
timing, global timing, live charts, recent slow ticks, the worst stage / current
bottleneck, and historical averages. Charts are painted programmatically with
QPainter — no third-party plotting library and no raster assets. The page only
observes and displays numbers; it starts no automation and changes no pipeline
behaviour. An optional offline benchmark button replays reviewed frames in a
background thread to populate the registry with no browser.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bap.gui import widgets
from bap.gui.theme import DARK
from bap.perf.registry import MetricsRegistry, get_registry


class Sparkline(QWidget):
    """A minimal filled line chart of recent values (ms). Programmatic, theme-aware."""

    def __init__(self, color: str = DARK.blue, parent=None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._color = color
        self.setMinimumHeight(72)

    def set_values(self, values) -> None:
        self._values = [float(v) for v in values]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(DARK.panel2))
        vals = self._values
        if len(vals) < 2:
            p.setPen(QPen(QColor(DARK.faint)))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no data yet")
            p.end()
            return
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        pad = 6
        n = len(vals)
        pts = []
        for i, v in enumerate(vals):
            x = pad + (w - 2 * pad) * (i / (n - 1))
            y = h - pad - (h - 2 * pad) * ((v - lo) / span)
            pts.append((x, y))
        pen = QPen(QColor(self._color)); pen.setWidthF(1.8)
        p.setPen(pen)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
        p.setPen(QPen(QColor(DARK.faint)))
        p.drawText(4, 14, f"max {hi:.1f} ms")
        p.drawText(4, h - 4, f"min {lo:.1f} ms")
        p.end()


class StageBars(QWidget):
    """Horizontal bars of mean stage cost (ms) — the pipeline breakdown."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stages: list[tuple[str, float]] = []
        self.setMinimumHeight(140)

    def set_stages(self, stages) -> None:
        self._stages = [(str(n), float(v)) for n, v in stages]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(DARK.panel2))
        if not self._stages:
            p.setPen(QPen(QColor(DARK.faint)))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no data yet")
            p.end()
            return
        hi = max(v for _, v in self._stages) or 1.0
        row_h = min(26, self.height() / max(1, len(self._stages)))
        label_w, pad = 108, 8
        bar_max = self.width() - label_w - 70
        colors = [DARK.blue, DARK.green, DARK.bronze, DARK.amber, DARK.violet, DARK.red]
        for i, (name, val) in enumerate(self._stages):
            y = int(i * row_h + 2)
            p.setPen(QPen(QColor(DARK.muted)))
            p.drawText(6, y + int(row_h) - 8, name)
            bw = int(bar_max * (val / hi))
            p.fillRect(label_w, y + 2, max(1, bw), int(row_h) - 8,
                       QColor(colors[i % len(colors)]))
            p.setPen(QPen(QColor(DARK.ink)))
            p.drawText(label_w + bw + 6, y + int(row_h) - 8, f"{val:.2f} ms")
        p.end()


_WORLD_COLS = ["World", "Ticks", "Skipped", "Avg", "Median", "p95", "Worst", "FPS", "Worst stage"]


class PerformancePage(QWidget):
    """The Performance nav page. Construct with a registry (defaults to the shared
    one) and call `refresh()` to repaint from the latest snapshot."""

    _bench_done = Signal()

    def __init__(self, registry: MetricsRegistry | None = None, parent=None) -> None:
        super().__init__(parent)
        self._registry = registry or get_registry()
        self._timer: QTimer | None = None
        self._bench_thread: threading.Thread | None = None
        self._build()
        self._bench_done.connect(self._on_bench_done)
        self.refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)
        v.addWidget(widgets.display_title("Performance"))
        v.addWidget(widgets.muted(
            "Measurement only — timing of the observe-only pipeline. Numbers come "
            "from the runtime and from offline benchmarks; nothing is clicked."
        ))

        # KPI tiles (global).
        kpis = QHBoxLayout(); kpis.setSpacing(12)
        self._kpi_worlds = widgets.StatTile("Worlds", "0", "attached / running", accent="bronze", icon_name="world")
        self._kpi_tick = widgets.StatTile("Avg tick", "—", "per World", accent="blue", icon_name="chart")
        self._kpi_fps = widgets.StatTile("FPS eq.", "—", "1 / mean tick", accent="green", icon_name="check")
        self._kpi_ram = widgets.StatTile("Peak RAM", "—", "process", accent="amber", icon_name="report")
        for t in (self._kpi_worlds, self._kpi_tick, self._kpi_fps, self._kpi_ram):
            kpis.addWidget(t, 1)
        v.addLayout(kpis)

        # Controls: World filter, refresh, offline benchmark.
        controls = QHBoxLayout()
        controls.addWidget(widgets.muted("View:"))
        self._world_combo = QComboBox()
        self._world_combo.addItem("All Worlds", None)
        self._world_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        controls.addWidget(self._world_combo)
        controls.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        self._bench_btn = QPushButton("Run offline benchmark")
        self._bench_btn.setProperty("primary", True)
        self._bench_btn.clicked.connect(self._run_benchmark)
        controls.addWidget(self._refresh_btn)
        controls.addWidget(self._bench_btn)
        v.addLayout(controls)

        # Charts: recent tick latency + stage breakdown.
        charts = QHBoxLayout(); charts.setSpacing(12)
        spark_card = widgets.Card("Recent tick latency", "ms per tick")
        self._spark = Sparkline()
        spark_card.body.addWidget(self._spark)
        charts.addWidget(spark_card, 1)
        bars_card = widgets.Card("Pipeline breakdown", "mean per stage")
        self._bars = StageBars()
        bars_card.body.addWidget(self._bars)
        charts.addWidget(bars_card, 1)
        v.addLayout(charts)

        # Bottleneck + system line.
        self._bottleneck = widgets.muted("")
        v.addWidget(self._bottleneck)
        self._system = widgets.muted("")
        v.addWidget(self._system)

        # Per-World timing table.
        table_card = widgets.Card("Per-World timing", "avg / median / p95 / worst (ms)")
        self._table = QTableWidget(0, len(_WORLD_COLS))
        self._table.setHorizontalHeaderLabels(_WORLD_COLS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        table_card.body.addWidget(self._table)
        v.addWidget(table_card, stretch=1)

        # Recent slow ticks.
        slow_card = widgets.Card("Recent slow ticks", "slowest observed")
        self._slow = QTableWidget(0, 3)
        self._slow.setHorizontalHeaderLabels(["World", "Total (ms)", "Worst stage"])
        self._slow.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._slow.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        slow_card.body.addWidget(self._slow)
        v.addWidget(slow_card)

    # --- live refresh ------------------------------------------------------

    def start_live(self, interval_ms: int = 1500) -> None:
        """Begin periodic refresh (real app only; tests call refresh() directly)."""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.refresh)
        self._timer.start(interval_ms)

    def stop_live(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def refresh(self) -> None:
        snap = self._registry.snapshot()
        self._sync_world_combo(snap)
        self._refresh_kpis(snap)
        self._refresh_charts(snap)
        self._refresh_tables(snap)

    def _sync_world_combo(self, snap: dict) -> None:
        names = sorted(snap.get("worlds", {}))
        existing = [self._world_combo.itemData(i) for i in range(self._world_combo.count())]
        if existing == [None, *names]:
            return
        prev = self._world_combo.currentData()
        self._world_combo.blockSignals(True)
        self._world_combo.clear()
        self._world_combo.addItem("All Worlds", None)
        for n in names:
            self._world_combo.addItem(n, n)
        if prev in names:
            self._world_combo.setCurrentIndex(names.index(prev) + 1)
        self._world_combo.blockSignals(False)

    def _selected_world(self) -> str | None:
        return self._world_combo.currentData()

    def _refresh_kpis(self, snap: dict) -> None:
        g = snap.get("global", {})
        self._kpi_worlds.set_value(str(snap.get("world_count", 0)),
                                   f"{snap.get('attached_worlds', 0)} att / {snap.get('running_worlds', 0)} run")
        mean = g.get("mean")
        self._kpi_tick.set_value(f"{mean:.1f} ms" if mean else "—",
                                 f"{snap.get('total_ticks', 0)} ticks")
        fps = g.get("fps")
        self._kpi_fps.set_value(f"{fps:.1f}" if fps else "—", "1 / mean tick")

    def _refresh_charts(self, snap: dict) -> None:
        world = self._selected_world()
        worlds = snap.get("worlds", {})
        # Sparkline: recent tick totals for the selected World (or the busiest).
        wm = self._registry.world(world) if world else self._pick_busiest()
        if wm is not None:
            self._spark.set_values([r.total * 1000 for r in wm.recent(120) if not r.skipped])
        # Stage bars: breakdown for the selected World, else global bottleneck view.
        if world and world in worlds:
            stages = worlds[world].get("stages", {})
        else:
            stages = self._global_stage_breakdown(worlds)
        ordered = [(n, s.get("mean", 0.0)) for n, s in stages.items()]
        self._bars.set_stages(ordered)

        bn = snap.get("current_bottleneck")
        if bn:
            self._bottleneck.setText(f"Current bottleneck:  {bn['stage']}  —  {bn['mean_ms']:.2f} ms mean")
        else:
            self._bottleneck.setText("Current bottleneck: (no data yet — run a benchmark or start the runtime)")

    def _pick_busiest(self):
        names = self._registry.world_names()
        best, best_n = None, -1
        for n in names:
            wm = self._registry.world(n)
            if wm and wm.tick_count > best_n:
                best, best_n = wm, wm.tick_count
        return best

    def _global_stage_breakdown(self, worlds: dict) -> dict:
        agg: dict[str, list[float]] = {}
        for w in worlds.values():
            for name, st in w.get("stages", {}).items():
                agg.setdefault(name, []).append(st.get("mean", 0.0))
        return {n: {"mean": sum(v) / len(v)} for n, v in agg.items() if v}

    def _refresh_tables(self, snap: dict) -> None:
        worlds = snap.get("worlds", {})
        rows = sorted(worlds.items())
        self._table.setRowCount(len(rows))
        for r, (name, w) in enumerate(rows):
            cells = [name, str(w.get("count", 0)), str(w.get("skipped_ticks", 0)),
                     f"{w.get('mean', 0):.2f}", f"{w.get('median', 0):.2f}",
                     f"{w.get('p95', 0):.2f}", f"{w.get('worst', 0):.2f}",
                     f"{w.get('fps', 0):.1f}", w.get("worst_stage") or "-"]
            for c, text in enumerate(cells):
                self._table.setItem(r, c, QTableWidgetItem(text))

        slow = snap.get("recent_slow_ticks", [])
        self._slow.setRowCount(len(slow))
        for r, rec in enumerate(slow):
            worst = max(rec.get("stages", {}).items(), key=lambda kv: kv[1], default=("-", 0))[0]
            for c, text in enumerate([rec.get("world", "?"), f"{rec.get('total_ms', 0):.2f}", worst]):
                self._slow.setItem(r, c, QTableWidgetItem(text))

        # Uptime + tick totals from the registry (system CPU/RAM come from the live
        # process sampler below and from benchmark reports).
        self._system.setText(
            f"Uptime {snap.get('uptime_s', 0):.0f}s  ·  {snap.get('total_ticks', 0)} ticks  ·  "
            f"{snap.get('total_skipped', 0)} skipped"
        )
        self._kpi_ram.set_value(*self._process_ram())

    def _process_ram(self):
        from bap.perf.system import current_rss_mb, peak_rss_mb

        peak = peak_rss_mb()
        cur = current_rss_mb()
        return (f"{peak:.0f} MB" if peak else "—", f"now {cur:.0f} MB" if cur else "process")

    # --- offline benchmark (background) ------------------------------------

    def _run_benchmark(self) -> None:
        if self._bench_thread is not None and self._bench_thread.is_alive():
            return
        self._bench_btn.setEnabled(False)
        self._bench_btn.setText("Running…")

        def work() -> None:
            try:
                # A short 2-World replay into this page's registry. Kept small on
                # purpose: each real detection tick is heavy (see the perf report),
                # so this is a live-display sample, not the full benchmark ladder —
                # that is `python -m bap.perf synthetic`.
                self._populate_registry(worlds=2, ticks=6)
            except Exception:  # never crash the UI over a benchmark
                pass
            finally:
                self._bench_done.emit()

        self._bench_thread = threading.Thread(target=work, daemon=True)
        self._bench_thread.start()

    def _populate_registry(self, *, worlds: int = 2, ticks: int = 6) -> None:
        """Replay a short synthetic run directly into this page's registry."""
        from bap.forge.detection.detector import BadgeDetector
        from bap.perf.benchmark import _make_world, build_classifier, load_frames
        from bap.perf.pipeline import run_tick

        frames = load_frames()
        clf = build_classifier()
        det = BadgeDetector()
        world_objs = [_make_world(i + 1) for i in range(worlds)]
        self._registry.set_world_counts(attached=len(world_objs), running=len(world_objs))
        n = len(frames)
        for step in range(ticks):
            for wi, world in enumerate(world_objs):
                idx = (step + wi) % n
                _, timer = run_tick(frames[idx].image, world=world, detector=det,
                                    classifier=clf, rois=frames[idx].rois)
                self._registry.record_tick(world.alias, timer)

    def _on_bench_done(self) -> None:
        self._bench_btn.setEnabled(True)
        self._bench_btn.setText("Run offline benchmark")
        self.refresh()


__all__ = ["PerformancePage", "Sparkline", "StageBars"]
