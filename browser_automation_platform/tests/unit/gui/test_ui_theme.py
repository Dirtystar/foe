"""Presentation layer (Milestone 4.8): theme, programmatic icons, reusable
widgets, and the Forge nav-shell. These lock in the redesign as presentation
only — behaviour is covered by the existing GUI suites and is untouched here."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QIcon

from bap.app.attended import TabAssignment
from bap.forge.worlds import World, WorldStore
from bap.gui import icons, theme, widgets
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


# --- theme -----------------------------------------------------------------


def test_build_qss_is_non_empty_and_styles_key_surfaces():
    qss = theme.build_qss(theme.DARK)
    assert isinstance(qss, str) and len(qss) > 500
    for selector in ("QMainWindow", "QPushButton", "QListWidget#navRail", 'QFrame[card="true"]'):
        assert selector in qss


def test_status_colors_resolve_to_palette_tokens():
    for token in set(theme.STATUS_COLORS.values()):
        assert isinstance(getattr(theme.DARK, token), str)


def test_apply_theme_sets_stylesheet(qapp):
    previous = qapp.styleSheet()
    try:
        theme.apply_theme(qapp)
        assert qapp.styleSheet()
    finally:
        qapp.setStyleSheet(previous)


# --- icons -----------------------------------------------------------------


def test_icons_render_to_qicon(qapp):
    assert icons.names()
    for name in icons.names():
        assert isinstance(icons.icon(name), QIcon)


# --- widgets ---------------------------------------------------------------


def test_card_exposes_body_layout(qapp):
    card = widgets.Card("Title", "note")
    assert card.body is not None
    card.set_note("changed")
    assert card.note.text() == "changed"


def test_stat_tile_updates_value(qapp):
    tile = widgets.StatTile("Worlds", "0", "configured")
    tile.set_value("3", "live")
    assert tile._value.text() == "3"
    assert tile._sub.text() == "live"


def test_status_pill_reflects_status(qapp):
    pill = widgets.StatusPill("Ready", "ready")
    assert "Ready" in pill.text()
    pill.set_status("Stopped", "stopped")
    assert "Stopped" in pill.text()


def test_nav_rail_emits_selected_key(qapp):
    rail = widgets.NavRail()
    rail.add_header("Overview")
    rail.add_section("dashboard", "Dashboard", "compass")
    rail.add_section("worlds", "Worlds", "shield")
    seen: list[str] = []
    rail.section_changed.connect(seen.append)
    rail.select("worlds")
    assert seen and seen[-1] == "worlds"


# --- Forge nav-shell -------------------------------------------------------


def _done(value=None):
    f: Future = Future()
    f.set_result(value)
    return f


class _Service:
    profile_ids = ()

    def add_world_session(self, spec):
        return _done()

    def stop_loop(self):
        pass


def _forge_window(qapp):
    store = WorldStore()
    store.add(World(alias="World H", hostname="cz8.forgeofempires.com"))
    store.add(World(alias="World F", hostname="cz1.forgeofempires.com"))
    return MainWindow(
        _Service(), QtReportBridge(), forge=True, world_store=store, assignment=TabAssignment()
    )


def test_nav_shell_has_all_pages_and_switches(qapp):
    win = _forge_window(qapp)
    try:
        for key in ("dashboard", "worlds", "vision", "review", "datasets", "reports", "settings"):
            assert key in win._pages
            win._show_page(key)
            assert win._stack.currentIndex() == win._pages[key]
    finally:
        win.close()


def test_dashboard_kpis_reflect_world_state(qapp):
    win = _forge_window(qapp)
    try:
        # Two configured worlds; none attached; browser closed; runtime stopped.
        assert win._kpi_worlds._value.text() == "2"
        assert win._kpi_attached._value.text() == "0"
        assert win._kpi_browser._value.text() == "Closed"
        assert win._kpi_runtime._value.text() == "Stopped"
    finally:
        win.close()
