"""Application theme — the "cartographer" dark visual language (Milestone 4.8).

Presentation only. This module holds the colour tokens and builds a single
application-wide Qt style sheet; it changes no behaviour and touches nothing
outside the GUI layer. All ornament is programmatic (gradients, borders) — no
image assets are shipped, and no third-party UI is copied.

Apply once on the QApplication (``apply_theme(app)``); every window then inherits
the theme. Widgets opt into specific styling through object names and dynamic
properties (see ``widgets.py``), so unstyled/offscreen test runs keep working.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Semantic colour tokens for one theme (hex strings)."""

    bg: str
    bg2: str
    panel: str
    panel2: str
    panel_hi: str
    line: str
    line2: str
    ink: str
    muted: str
    faint: str
    bronze: str
    bronze_dim: str
    blue: str
    blue_soft: str
    green: str
    amber: str
    red: str
    violet: str


DARK = Palette(
    bg="#121017", bg2="#0E0C12",
    panel="#1B1822", panel2="#211D2A", panel_hi="#262130",
    line="rgba(214,186,132,0.10)", line2="rgba(255,255,255,0.05)",
    ink="#ECE6DA", muted="#9C93A6", faint="#6E6678",
    bronze="#C89B5E", bronze_dim="#8C6E42",
    blue="#5EA8EA", blue_soft="rgba(94,168,234,0.14)",
    green="#5FB98A", amber="#E0B454", red="#DE7B6B", violet="#9C86D8",
)


def build_qss(p: Palette = DARK) -> str:
    """Return the application-wide style sheet for a palette."""
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", system-ui, "DejaVu Sans", sans-serif;
        font-size: 13px;
        color: {p.ink};
    }}
    QMainWindow, QDialog, QWidget#page, QWidget#appRoot {{
        background: {p.bg};
    }}
    QToolTip {{
        background: {p.panel_hi}; color: {p.ink};
        border: 1px solid {p.line}; padding: 6px 8px; border-radius: 6px;
    }}

    /* --- generic surfaces --- */
    QGroupBox {{
        background: {p.panel}; border: 1px solid {p.line};
        border-radius: 14px; margin-top: 14px; padding: 14px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 14px; top: 2px; padding: 0 4px;
        color: {p.muted}; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
    }}

    /* card frame (widgets.Card) */
    QFrame[card="true"] {{
        background: {p.panel2}; border: 1px solid {p.line};
        border-radius: 14px;
    }}
    QLabel[role="display"] {{
        font-family: "Georgia", "Spectral", serif; font-size: 20px; color: {p.ink};
    }}
    QLabel[role="ctitle"] {{
        color: {p.muted}; font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase;
    }}
    QLabel[role="muted"] {{ color: {p.muted}; }}
    QLabel[role="faint"] {{ color: {p.faint}; font-size: 12px; }}
    QLabel[role="kpi"] {{ font-size: 30px; font-weight: 700; color: {p.ink}; }}

    /* --- buttons --- */
    QPushButton {{
        background: {p.panel_hi}; color: {p.ink};
        border: 1px solid {p.line}; border-radius: 10px;
        padding: 8px 14px; font-weight: 600;
    }}
    QPushButton:hover {{ border-color: {p.bronze_dim}; background: {p.panel_hi}; }}
    QPushButton:pressed {{ background: {p.panel}; }}
    QPushButton:disabled {{ color: {p.faint}; border-color: {p.line2}; background: {p.panel}; }}
    QPushButton[primary="true"] {{
        background: {p.blue}; color: #0C1622; border: 1px solid #7BC0FF; font-weight: 700;
    }}
    QPushButton[primary="true"]:hover {{ background: #6FB3EE; }}
    QPushButton[primary="true"]:disabled {{ background: {p.panel}; color: {p.faint}; border-color: {p.line2}; }}
    QPushButton[danger="true"]:hover {{ border-color: {p.red}; color: {p.red}; }}
    QPushButton[ghost="true"] {{ background: transparent; }}

    /* --- inputs --- */
    QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QTextEdit {{
        background: {p.panel}; color: {p.ink};
        border: 1px solid {p.line}; border-radius: 10px; padding: 7px 10px;
        selection-background-color: {p.blue_soft};
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {{
        border-color: {p.blue};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.panel_hi}; border: 1px solid {p.line};
        selection-background-color: {p.blue_soft}; outline: 0;
    }}
    QPlainTextEdit {{ font-family: "JetBrains Mono", "Consolas", monospace; font-size: 12px; }}

    /* --- tables --- */
    QTableWidget, QTableView {{
        background: {p.panel}; border: 1px solid {p.line}; border-radius: 12px;
        gridline-color: {p.line2}; alternate-background-color: {p.panel2};
    }}
    QHeaderView::section {{
        background: {p.panel2}; color: {p.faint};
        border: none; border-bottom: 1px solid {p.line};
        padding: 9px 10px; font-size: 11px; letter-spacing: 0.6px; text-transform: uppercase;
    }}
    QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {p.line2}; }}
    QTableWidget::item:selected {{ background: {p.blue_soft}; color: {p.ink}; }}

    /* --- scrollbars --- */
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.panel_hi}; border-radius: 6px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.bronze_dim}; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.panel_hi}; border-radius: 6px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

    /* --- menus / tabs --- */
    QMenuBar {{ background: {p.bg2}; color: {p.muted}; }}
    QMenuBar::item:selected {{ background: {p.panel_hi}; color: {p.ink}; }}
    QMenu {{ background: {p.panel_hi}; border: 1px solid {p.line}; }}
    QMenu::item:selected {{ background: {p.blue_soft}; }}
    QTabWidget::pane {{ border: 1px solid {p.line}; border-radius: 12px; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {p.muted}; padding: 8px 16px;
        border-top-left-radius: 10px; border-top-right-radius: 10px;
    }}
    QTabBar::tab:selected {{ background: {p.panel}; color: {p.ink}; }}

    /* --- navigation rail --- */
    QListWidget#navRail {{
        background: {p.bg2}; border: none; border-right: 1px solid {p.line};
        outline: 0; padding: 8px;
    }}
    QListWidget#navRail::item {{
        color: {p.muted}; padding: 10px 12px; border-radius: 10px; margin: 2px 4px;
    }}
    QListWidget#navRail::item:hover {{ background: {p.panel}; color: {p.ink}; }}
    QListWidget#navRail::item:selected {{ background: {p.blue_soft}; color: {p.ink}; }}

    /* --- status pill (widgets.StatusPill) --- */
    QLabel[pill="true"] {{
        border-radius: 11px; padding: 5px 11px; font-size: 12px; font-weight: 600;
        background: {p.panel}; border: 1px solid {p.line}; color: {p.muted};
    }}
    QFrame#footerBar, QFrame#toolBar, QFrame#titleBar {{
        background: {p.bg2}; border: none;
    }}
    QFrame#footerBar {{ border-top: 1px solid {p.line}; }}
    QFrame#titleBar {{ border-bottom: 1px solid {p.line}; }}
    """


def apply_theme(app, palette: Palette = DARK) -> None:
    """Apply the theme to a QApplication. Safe to call once at startup."""
    app.setStyleSheet(build_qss(palette))


# Convenience colour lookups for code that paints (e.g. status dots).
def color(name: str, palette: Palette = DARK) -> str:
    return getattr(palette, name)


STATUS_COLORS = {
    "running": "green", "ok": "green", "ready": "green", "attached": "green",
    "open": "blue", "scanning": "blue",
    "stopped": "faint", "closed": "faint", "idle": "faint",
    "unknown": "amber", "warn": "amber",
    "error": "red", "stop": "red", "danger": "red",
}


__all__ = ["Palette", "DARK", "build_qss", "apply_theme", "color", "STATUS_COLORS"]
