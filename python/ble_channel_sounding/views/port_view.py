from PyQt6 import QtCore, QtWidgets as W
from .layout import compact_form

SIMULATOR = "Simulator"


class PortView(W.QWidget):
    """Serial port settings; the Connect action lives in the top panel's button row."""
    connect_requested = QtCore.pyqtSignal(str, int)
    status_message = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rejected = {}  # device -> reason of its last failed connect
        form = compact_form(self)
        self.port = W.QComboBox()
        self.port.setEditable(True)
        self.baud = W.QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(["115200", "460800", "921600", "1000000"])
        self.baud.setCurrentText("921600")
        row = W.QHBoxLayout()
        row.addWidget(self.port, 1)
        refresh = W.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        form.addRow("Port", row)
        form.addRow("Baud", self.baud)
        self.refresh()

    def refresh(self):
        from serial.tools.list_ports import comports
        previous = self.port.currentData() or self.port.currentText()
        self.port.clear()
        for p in comports():
            usb = f" {p.vid:04x}:{p.pid:04x}" if p.vid is not None and p.pid is not None else ""
            self.port.addItem(f"{p.device} — {p.description}{usb}", p.device)
            self._show_rejection(self.port.count() - 1)
        self.port.addItem(f"{SIMULATOR} — in-memory client", SIMULATOR)
        self._show_rejection(self.port.count() - 1)
        if previous:
            index = self.port.findData(previous)
            self.port.setCurrentIndex(index)
            if index < 0:
                self.port.setEditText(previous)

    def mark_rejected(self, device, reason):
        """Flag a port whose connect failed; the flag survives Refresh and clears on success."""
        self.rejected[device] = reason
        index = self.port.findData(device)
        if index >= 0:
            self._show_rejection(index)

    def clear_rejected(self, device):
        self.rejected.pop(device, None)
        index = self.port.findData(device)
        if index >= 0:
            self._show_rejection(index)

    def _show_rejection(self, index):
        device = self.port.itemData(index)
        text = self.port.itemText(index).split(" — rejected: ")[0]
        reason = self.rejected.get(device)
        self.port.setItemText(index, f"{text} — rejected: {reason}" if reason else text)
        self.port.setItemData(index, reason or "", QtCore.Qt.ItemDataRole.ToolTipRole)

    def connect_port(self):
        try:
            baud = int(self.baud.currentText())
            if baud <= 0:
                raise ValueError()
        except ValueError:
            self.status_message.emit("Enter a positive baud rate")
            return
        self.connect_requested.emit(self.port.currentData() or self.port.currentText(), baud)
