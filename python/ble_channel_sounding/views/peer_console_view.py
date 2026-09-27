"""Controls for an optional second serial port carrying peer-console output."""

from PyQt6 import QtCore, QtWidgets as W
from .layout import compact_form


class PeerConsoleView(W.QWidget):
    open_requested = QtCore.pyqtSignal(str, int)
    close_requested = QtCore.pyqtSignal()
    settings_changed = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        form = compact_form(self)
        self.port = W.QLineEdit()
        self.port.setPlaceholderText("Second serial port, e.g. /dev/cu.usbmodem…")
        self.port.setToolTip("Read-only console input from the other device; it is not part of client configuration.")
        self.baud = W.QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(["115200", "460800", "921600", "1000000"])
        self.baud.setCurrentText("921600")
        row = W.QHBoxLayout()
        row.addWidget(self.port, 1)
        self.button = W.QPushButton("Open peer console")
        self.button.setCheckable(True)
        self.button.clicked.connect(self.toggle)
        self.port.textChanged.connect(self._settings_edited)
        self.baud.currentTextChanged.connect(self._settings_edited)
        row.addWidget(self.button)
        form.addRow("Port", row)
        form.addRow("Baud", self.baud)

    def settings(self):
        try:
            baud = int(self.baud.currentText())
        except ValueError:
            baud = 921600
        return {"port": self.port.text().strip(), "baud": baud}

    def set_settings(self, settings):
        settings = settings if isinstance(settings, dict) else {}
        port = str(settings.get("port", ""))
        baud = str(settings.get("baud", 921600))
        self.port.blockSignals(True)
        self.baud.blockSignals(True)
        self.port.setText(port)
        self.baud.setCurrentText(baud)
        self.baud.blockSignals(False)
        self.port.blockSignals(False)

    def _settings_edited(self, *_):
        self.settings_changed.emit(self.settings())

    def toggle(self):
        if self.button.isChecked():
            try:
                baud = int(self.baud.currentText())
                if baud <= 0 or not self.port.text().strip():
                    raise ValueError
            except ValueError:
                self.button.setChecked(False)
                self.button.setText("Open peer console")
                return
            self.button.setText("Close peer console")
            self.open_requested.emit(self.port.text().strip(), baud)
        else:
            self.button.setText("Open peer console")
            self.close_requested.emit()

    def set_opened(self, opened):
        self.button.blockSignals(True)
        self.button.setChecked(bool(opened))
        self.button.setText("Close peer console" if opened else "Open peer console")
        self.button.blockSignals(False)
        self.port.setEnabled(not opened)
        self.baud.setEnabled(not opened)
