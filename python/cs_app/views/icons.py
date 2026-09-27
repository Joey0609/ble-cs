"""Toolbar icons drawn from inline SVG, so they look the same on every platform and icon theme."""

from PyQt6 import QtCore, QtGui, QtSvg

COLOR = "#21334b"
# 24 × 24 outline glyphs with the usual meaning of each action.
PATHS = {
    "help": ('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.3 1.7c-1.1.9-1.8 1.3-1.8 2.8"/>'
             '<path d="M12 17h.01"/>'),
    # Plug: open the serial link to the board.
    "connect": ('<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/>'
                '<path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/>'),
    # Magnifier over a Bluetooth mark: scan for nearby peers.
    "scan": ('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 6 6"/>'
             '<path d="M10 7v7l3-2.5-3-2 3-2.5-3-2"/>'),
    # Bluetooth link, shown until a peer is connected.
    "link-connect": '<path d="M7 7l10 10-5 5V2l5 5L7 17"/>',
    # Plug pulled out: close the serial link to the board.
    "unplug": ('<path d="m19 5 3-3"/><path d="m2 22 3-3"/>'
               '<path d="M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4z"/>'
               '<path d="M7.5 13.5 10 11"/><path d="M10.5 16.5 13 14"/>'
               '<path d="m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0z"/>'),
    # Upload to device: push the host configuration to the board.
    "apply": ('<path d="m16 6-4-4-4 4"/><path d="M12 2v8"/><rect x="2" y="14" width="20" height="8" rx="2"/>'
              '<path d="M6 18h.01M10 18h.01"/>'),
    # Two-way arrows: compare host and device configuration, then get or apply.
    "sync": '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/>',
    "start": '<path d="m7 4 13 8-13 8z" fill="{color}"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="{color}"/>',
    "record": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5" fill="#d32f2f" stroke="none"/>',
    # Pencil on a line: write a description for the session being recorded.
    "describe": ('<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/><path d="m14 6 4 4"/>'
                 '<path d="M12 20h9"/>'),
    # Bluetooth off: drop the radio link, which also ends the session.
    "disconnect": '<path d="m17 17-5 5V12l-5 5"/><path d="m2 2 20 20"/><path d="M14.5 9.5 17 7l-5-5v4.5"/>',
    # Crossed circle: abandon the connection attempt still waiting for an answer.
    "cancel": '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "open": ('<path d="M3 18V6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v2"/>'
             '<path d="M3 18l3-7h16l-3 7z"/>'),
    # Eraser: clear the shown results, the open capture and the session timeline.
    "clear": ('<path d="m7 21-4.3-4.3a2 2 0 0 1 0-2.8l9.6-9.6a2 2 0 0 1 2.8 0l5.6 5.6a2 2 0 0 1 0 2.8L13 21"/>'
              '<path d="M22 21H7"/><path d="m5 11 9 9"/>'),
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
    path = PATHS[name].replace("{color}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{path}</svg>')
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
