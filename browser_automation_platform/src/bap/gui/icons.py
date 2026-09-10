"""Original line-icon set, rendered programmatically to QIcon (Milestone 4.8).

Each icon is an inline SVG path drawn on a 24×24 grid with a configurable stroke
colour — original glyphs, no third-party icon set and no raster assets. Icons are
rendered on demand and cached. Falls back to an empty QIcon if Qt SVG is missing,
so nothing here can crash a headless run.
"""

from __future__ import annotations

from functools import lru_cache

# name -> inner SVG markup (stroke uses currentColor via {stroke}).
_PATHS = {
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15 9-4 1.6L9 15l4-1.6L15 9Z"/>',
    "shield": '<path d="M12 3 5 5.6v5.2c0 4 2.9 6.6 7 8 4.1-1.4 7-4 7-8V5.6L12 3Z"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.6"/>',
    "quill": '<path d="M4 20c2-6 8-12 15-15l1 1C17 13 11 19 5 21l-1-1Z"/><path d="m14 6 4 4"/>',
    "datasets": '<path d="M4 7c0-1.4 3.6-2.5 8-2.5S20 5.6 20 7s-3.6 2.5-8 2.5S4 8.4 4 7Z"/>'
                '<path d="M4 7v10c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V7M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5"/>',
    "report": '<path d="M7 4h8l3 3v13H7z"/><path d="M15 4v3h3M10 12h5M10 16h5"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1'
            'M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    "badge": '<circle cx="12" cy="12" r="8"/><path d="m15 9-4 1.6L9 15l4-1.6L15 9Z"/>',
    "chart": '<path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/>',
    "power": '<path d="M12 3v9M6.5 7a8 8 0 1 0 11 0"/>',
    "world": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
}


def _svg(name: str, stroke: str, width: float) -> bytes:
    inner = _PATHS.get(name, "")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{inner}</svg>'
    ).encode("utf-8")


@lru_cache(maxsize=256)
def icon(name: str, stroke: str = "#C89B5E", size: int = 22, width: float = 1.7):
    """Return a QIcon for `name` stroked in `stroke`. Cached by arguments."""
    from PySide6.QtGui import QIcon

    try:
        from PySide6.QtCore import QByteArray, QSize, Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(QByteArray(_svg(name, stroke, width)))
        pm = QPixmap(QSize(size, size))
        pm.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter

        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        return QIcon(pm)
    except Exception:  # pragma: no cover - Qt SVG unavailable
        return QIcon()


def names() -> list[str]:
    return list(_PATHS)


__all__ = ["icon", "names"]
