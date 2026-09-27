"""Controls shared by the top-level configuration toolbar and CS setup."""
from PyQt6 import QtCore, QtWidgets as W
from ..protocol.packets import OperationMode
from ..log_config import DEFAULT_LOG, LEVEL_LABELS, normalize_log
from .control_help import GENERAL_CONTROL_HELP
from .layout import compact_form

MODE_CHOICES = ((OperationMode.CS_INITIATOR, "CS"),
                (OperationMode.HOSTLESS_CS, "CS Hostless"),
                (OperationMode.RADIO_TX_TEST, "Radio Test (disabled)"))
CENTRAL = 0


class GeneralView(W.QWidget):
    selected = QtCore.pyqtSignal(object)
    name_changed = QtCore.pyqtSignal(str)
    gap_role_changed = QtCore.pyqtSignal(int)
    patterns_changed = QtCore.pyqtSignal(list)
    log_changed = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        form = self.form = compact_form(self)
        self.mode = W.QComboBox()
        for mode, label in MODE_CHOICES:
            self.mode.addItem(label, mode)
        radio_index = self.mode.findData(OperationMode.RADIO_TX_TEST)
        self.mode.model().item(radio_index).setEnabled(False)
        self.mode.setItemData(
            radio_index,
            "Radio Test is temporarily disabled in this application build",
            QtCore.Qt.ItemDataRole.ToolTipRole,
        )
        self.mode.setToolTip(GENERAL_CONTROL_HELP["operation_mode"])
        self.mode.currentIndexChanged.connect(lambda: self.selected.emit(self.mode.currentData()))
        self.gap_role = W.QComboBox()
        self.gap_role.addItem("Central", CENTRAL)
        self.gap_role.addItem("Peripheral", 1)
        self.gap_role.setToolTip(GENERAL_CONTROL_HELP["gap_role"])
        self.gap_role.currentIndexChanged.connect(self.gap_role_edited)
        self.patterns = W.QPlainTextEdit()
        self.patterns.setPlaceholderText("Peripheral name prefixes, one per line (1–8)")
        self.patterns.setToolTip(GENERAL_CONTROL_HELP["peripheral_patterns"])
        self.patterns.setMaximumHeight(60)
        self.patterns.textChanged.connect(lambda: self.patterns_changed.emit(self.patterns.toPlainText().splitlines()))
        self.device_name = W.QLineEdit()
        self.device_name.setPlaceholderText("Firmware default (CS Client)")
        self.device_name.setToolTip(GENERAL_CONTROL_HELP["device_name"])
        self.device_name.textChanged.connect(self.name_changed.emit)
        self.log_group = W.QGroupBox("Client log")
        log_form = compact_form(self.log_group)
        self.log_controls = {}
        for key, label in (("console", "Console"), ("host", "Host")):
            control = W.QComboBox()
            for level, text in LEVEL_LABELS.items():
                control.addItem(text, level)
            control.setToolTip(GENERAL_CONTROL_HELP[f"log_{key}"])
            control.currentIndexChanged.connect(self.log_edited)
            self.log_controls[key] = control
            log_form.addRow(label, control)
        self.set_log(DEFAULT_LOG)

    def gap_role_edited(self):
        self.update_rows()
        self.gap_role_changed.emit(self.gap_role.currentData())

    def update_rows(self):
        # These controls are owned by the top toolbar or CS setup in the
        # integrated application; this holder has no General configuration tab.
        return

    def log_config(self):
        """Return the plan-friendly console/host levels."""
        return {key: control.currentData() for key, control in self.log_controls.items()}

    def set_log(self, value):
        """Show log levels without emitting an edit signal."""
        levels = normalize_log(value)
        blockers = [QtCore.QSignalBlocker(control) for control in self.log_controls.values()]
        try:
            for key, level in levels.items():
                control = self.log_controls[key]
                index = control.findData(level)
                if index < 0:
                    control.addItem(f"Unknown ({level})", level)
                    index = control.count() - 1
                control.setCurrentIndex(index)
        finally:
            del blockers

    def log_edited(self, *_):
        self.log_changed.emit(self.log_config())

    def set_device_name(self, name):
        with QtCore.QSignalBlocker(self.device_name):
            self.device_name.setText(name or "")

    def set_host(self, gap_role, patterns):
        """Show the CS host GAP role and scan prefixes without emitting changes."""
        with QtCore.QSignalBlocker(self.gap_role), QtCore.QSignalBlocker(self.patterns):
            index = self.gap_role.findData(gap_role)
            if index < 0:
                self.gap_role.addItem(f"Unknown ({gap_role})", gap_role)
                index = self.gap_role.count() - 1
            self.gap_role.setCurrentIndex(index)
            text = "\n".join(patterns)
            if self.patterns.toPlainText() != text:
                self.patterns.setPlainText(text)
        self.update_rows()

    def set_mode(self, mode):
        """Show mode without emitting selected."""
        mode = OperationMode(mode)
        if mode == OperationMode.RADIO_TX_TEST:
            mode = OperationMode.CS_INITIATOR
        hostless = mode == OperationMode.HOSTLESS_CS
        self.device_name.setEnabled(mode not in (OperationMode.RADIO_TX_TEST, OperationMode.HOSTLESS_CS))
        # Hostless firmware owns its logging configuration and the receive-only
        # hostless session cannot send a log-level command. These controls are
        # moved into the top toolbar by MainWindow, so disable them directly
        # instead of relying on log_group's parent/child relationship.
        for control in self.log_controls.values():
            control.setEnabled(not hostless)
        mode = OperationMode.CS_INITIATOR if mode == OperationMode.CS_REFLECTOR else mode
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData(mode))
        self.mode.blockSignals(False)
        self.update_rows()

    def set_supported_modes(self, mask):
        model = self.mode.model()
        for index in range(self.mode.count()):
            mode = self.mode.itemData(index)
            # Hostless CS is a host-side session mode and is not advertised as a
            # separate firmware operation-mode bit.
            supported = mode != OperationMode.RADIO_TX_TEST and (mode == OperationMode.HOSTLESS_CS or (
                bool(mask & (1 << OperationMode.CS_INITIATOR)) if mode == OperationMode.CS_INITIATOR
                else bool(mask & (1 << mode))))
            model.item(index).setEnabled(supported)
            tooltip = ("Radio Test is temporarily disabled in this application build"
                       if mode == OperationMode.RADIO_TX_TEST else
                       "" if supported else "This firmware does not support this mode")
            self.mode.setItemData(index, tooltip, QtCore.Qt.ItemDataRole.ToolTipRole)
