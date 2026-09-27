"""In-place table and list updates for views refreshed while reports arrive."""
from PyQt6 import QtCore, QtGui, QtWidgets as W


class RelativeColumns(QtCore.QObject):
    """Keep column widths a share of the view width; dragging a column changes its share.

    Columns may together be wider than the view, which then scrolls horizontally.
    """

    def __init__(self, view: W.QAbstractItemView, shares):
        super().__init__(view)
        self.view, self.shares, self.applying = view, list(shares), False
        self.header = view.header() if isinstance(view, W.QTreeView) else view.horizontalHeader()
        self.header.setStretchLastSection(False)
        self.header.setSectionResizeMode(W.QHeaderView.ResizeMode.Interactive)
        self.header.sectionResized.connect(self.resized)
        view.viewport().installEventFilter(self)
        self.apply()

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Type.Resize:
            self.apply()
        return False

    def apply(self):
        width = self.view.viewport().width()
        self.applying = True
        for column, share in enumerate(self.shares):
            self.header.resizeSection(column, max(self.header.minimumSectionSize(), round(share * width)))
        self.applying = False

    def resized(self, column, _old, new):
        width = self.view.viewport().width()
        if not self.applying and column < len(self.shares) and width > 0:
            self.shares[column] = new / width


def set_cell(table: W.QTableWidget, row: int, column: int, text: str, background=None) -> None:
    """Update a cell in place, so live refreshes keep the selection, current cell and scroll position."""
    item = table.item(row, column)
    if item is None:
        item = W.QTableWidgetItem(text)
        table.setItem(row, column, item)
    elif item.text() != text:
        item.setText(text)
    item.setBackground(QtGui.QBrush() if background is None else background)


def set_list(widget: W.QListWidget, entries) -> None:
    """Show (text, background or None) entries, updating existing items so the selection is kept."""
    entries = list(entries)
    while widget.count() > len(entries):
        widget.takeItem(widget.count() - 1)
    for row, (text, background) in enumerate(entries):
        item = widget.item(row)
        if item is None:
            item = W.QListWidgetItem(text)
            widget.addItem(item)
        elif item.text() != text:
            item.setText(text)
        item.setBackground(QtGui.QBrush() if background is None else background)


def make_table(headers) -> W.QTableWidget:
    """A read-only, row-selecting table with the given column headers."""
    table = W.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def fill_table(table: W.QTableWidget, rows, resize=True) -> None:
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            set_cell(table, r, c, "" if value is None else str(value))
    if resize:
        table.resizeColumnsToContents()
