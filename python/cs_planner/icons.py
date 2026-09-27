"""Toolbar icons drawn from inline SVG, so they look the same on every platform and icon theme."""

from PyQt6 import QtCore, QtGui, QtSvg

COLOR = "#21334b"
# 24 × 24 outline glyphs with the usual meaning of each action.
PATHS = {
    "open": ('<path d="M3 18V6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v2"/>'
             '<path d="M3 18l3-7h16l-3 7z"/>'),
    "save": ('<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 1-2z"/>'
             '<path d="M8 3v5h7V3"/><path d="M8 21v-7h8v7"/>'),
    "export-code": ('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>'
                    '<path d="M10 12.5l-2.5 3 2.5 3"/><path d="M14 12.5l2.5 3-2.5 3"/>'),
    "export-image": ('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/>'
                     '<path d="M3 17l5-5 4 4 3-3 6 6"/>'),
    "fit": ('<path d="M4 9V4h5"/><path d="M15 4h5v5"/><path d="M20 15v5h-5"/><path d="M9 20H4v-5"/>'
            '<rect x="9" y="9" width="6" height="6" rx="1"/>'),
    "reset": '<path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/><path d="M3 3v5h5"/>',
}


def icon(name, color=COLOR):
    """QIcon of glyph name, rendered for 1× to 3× device pixel ratios."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>')
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode()))
    result = QtGui.QIcon()
    for size in (16, 18, 24, 32, 36, 48, 54, 72):
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result
