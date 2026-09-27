"""Tooltips that wrap at half the width of their main window."""

from html import escape
import re

from PyQt6 import QtCore, QtGui, QtWidgets as W

RICH_TEXT = re.compile(r"</?[a-zA-Z][^>]*>")
MINIMUM_PX = 150


def main_window(widget):
    """The top-level window of widget, looking through popups such as combo box lists."""
    window = widget.window()
    while window.parentWidget() is not None:
        window = window.parentWidget().window()
    return window


def half_window_width(widget):
    return main_window(widget).width() // 2


def tooltip_html(text, width):
    """Return (rich text, text width in px): a table of width px when the text is wider than that."""
    body = text if RICH_TEXT.search(text) else escape(text).replace("\n", "<br>")
    document = QtGui.QTextDocument()
    document.setDefaultFont(W.QToolTip.font())
    document.setHtml(body)
    natural = document.idealWidth()
    if natural <= width:
        return f"<qt>{body}</qt>", natural
    return f'<qt><table width="{width}" cellspacing="0" cellpadding="0"><tr><td>{body}</td></tr></table></qt>', width


def fit_tooltip(text, widget, frame_px=0):
    """Return text as rich text no wider than half of widget's main window less frame_px.

    Without text or a widget the text is returned unchanged.
    """
    if not text or widget is None:
        return text
    return tooltip_html(text, max(MINIMUM_PX, half_window_width(widget) - frame_px))[0]


def show_tooltip(pos, text, widget):
    """Show text at pos wrapped to half of widget's main window and return the text shown.

    The tooltip frame (border, padding, margins) depends on the style and style
    sheets, so it is measured on the shown tooltip; one that is too wide is shown
    again with its text narrowed by that frame.
    """
    if not text or widget is None:
        W.QToolTip.showText(pos, text, widget)
        return text
    half = half_window_width(widget)
    shown, text_px = tooltip_html(text, max(MINIMUM_PX, half))
    W.QToolTip.showText(pos, shown, widget)
    label = next((top for top in W.QApplication.topLevelWidgets()
                  if top.objectName() == "qtooltip_label" and top.isVisible()), None)
    if label is not None and label.width() > half:
        shown = fit_tooltip(text, widget, label.width() - int(text_px))
        W.QToolTip.showText(pos, shown, widget)
    return shown


class TooltipWidthFilter(QtCore.QObject):
    """Application event filter that shows widget, item view, tab and graphics item tooltips through show_tooltip."""

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.Type.ToolTip or not isinstance(obj, W.QWidget):
            return False
        text = self.text_at(obj, event.pos())
        if not text:
            return False  # Qt's default handling, including propagation to the parent
        show_tooltip(event.globalPos(), text, obj)
        return True

    @staticmethod
    def text_at(widget, pos):
        parent = widget.parentWidget()
        if isinstance(parent, W.QHeaderView):
            return None
        if isinstance(parent, W.QAbstractItemView) and widget is parent.viewport():
            try:
                index = parent.indexAt(pos)
            except RuntimeError:
                return None
            return index.data(QtCore.Qt.ItemDataRole.ToolTipRole)
        if isinstance(parent, W.QGraphicsView) and widget is parent.viewport():
            item = parent.itemAt(pos)
            while item is not None and not item.toolTip():
                item = item.parentItem()
            return item.toolTip() if item is not None else None
        if isinstance(widget, W.QTabBar):
            return widget.tabToolTip(widget.tabAt(pos))
        return widget.toolTip()


def install(app):
    """Wrap every tooltip of app; the filter is owned by app."""
    tooltip_filter = TooltipWidthFilter(app)
    app.installEventFilter(tooltip_filter)
    return tooltip_filter
