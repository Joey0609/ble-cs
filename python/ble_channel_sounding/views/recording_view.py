"""Recording settings: logging switch, output folder and MATLAB conversion."""
from datetime import datetime
from pathlib import Path
from PyQt6 import QtCore, QtWidgets as W
from .layout import compact_form


def recording_name(mode, started):
    """<mode>_<day>_<Mon>_<year>_<hour>_<minute>_<second>.h5, e.g. cs_initiator_14_Sep_2026_13_05_22.h5."""
    return f"{mode.name.lower()}_{started:%d_%b_%Y_%H_%M_%S}.h5"


class RecordingView(W.QGroupBox):
    converted = QtCore.pyqtSignal(str)
    save_session_requested = QtCore.pyqtSignal()
    history_limit_changed = QtCore.pyqtSignal(int)  # bytes

    def __init__(self, parent=None):
        super().__init__("Recording", parent)
        self.last_path = None
        # A compact, analysis-oriented default. Raw frames remain available
        # in the HDF5 recording and can be enabled for a MAT export when needed.
        self.mat_options = {"include_groups": {"config", "results", "host_log"}, "include_meta": False}
        form = compact_form(self)
        self.description = W.QLineEdit()
        self.description.setPlaceholderText("Optional run description")
        self.description.setToolTip("Saved in the recording metadata; newlines can be added after the run.")
        form.addRow("Description", self.description)
        row = W.QHBoxLayout()
        self.logging = W.QCheckBox("Record each run")
        row.addWidget(self.logging)
        self.folder = W.QLineEdit("recordings")
        self.folder.setPlaceholderText("Recording output folder")
        self.folder.setToolTip("Recording output folder")
        row.addWidget(self.folder, 1)
        browse = W.QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        form.addRow("Folder", row)
        row = W.QHBoxLayout()
        self.convert_last = W.QPushButton("Convert last")
        self.convert_last.setToolTip("Write the last finished recording as a MATLAB file next to it")
        self.convert_last.setEnabled(False)
        self.convert_last.clicked.connect(lambda: self.convert(self.last_path))
        row.addWidget(self.convert_last)
        self.convert_other = W.QPushButton("Convert file…")
        self.convert_other.setToolTip("Choose an HDF5 recording and write it as a MATLAB file next to it")
        self.convert_other.clicked.connect(self.choose_and_convert)
        row.addWidget(self.convert_other)
        self.configure_mat = W.QPushButton("MAT options…")
        self.configure_mat.setToolTip("Choose which HDF5 sections are exported to MATLAB")
        self.configure_mat.clicked.connect(self.configure_mat_export)
        row.addWidget(self.configure_mat)
        self.save_session = W.QPushButton("Save session…")
        self.save_session.setToolTip("Save the whole session history (also unrecorded and hostless sessions) "
                                     "as an HDF5 recording")
        self.save_session.setEnabled(False)
        self.save_session.clicked.connect(self.save_session_requested)
        row.addWidget(self.save_session)
        self.file = W.QLabel()
        self.file.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
        row.addWidget(self.file, 1)
        form.addRow("To MAT", row)
        self.history_limit = W.QDoubleSpinBox(minimum=0.1, maximum=1024.0, value=2.0, decimals=1, singleStep=0.5,
                                              suffix=" GB")
        self.history_limit.setToolTip("Disk bound of the temporary session history. Above it the oldest "
                                      "records are dropped and the Session tab says where the kept history "
                                      "starts. Applies from the next session.")
        self.history_limit.valueChanged.connect(lambda value: self.history_limit_changed.emit(self.history_bytes()))
        form.addRow("Session history", self.history_limit)

    def history_bytes(self) -> int:
        return int(self.history_limit.value() * 2**30)

    def browse(self):
        folder = W.QFileDialog.getExistingDirectory(self, "Recording folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def path_for(self, mode, started=None, prefix=""):
        folder = Path(self.folder.text())
        path = folder / (prefix + recording_name(mode, started or datetime.now()))
        suffix = 2
        while path.exists():  # two runs within one second; recordings are never replaced
            path = path.with_stem(f"{path.stem.rsplit('__', 1)[0]}__{suffix}")
            suffix += 1
        return path

    def session_path_for(self, mode, started=None):
        """session_<mode>_<start time>.h5 in the recording folder, for *Save session…*."""
        return self.path_for(mode, started, prefix="session_")

    @staticmethod
    def config_path_for(recording):
        """config_<recording stem>.json beside the recording, e.g. config_cs_initiator_14_Sep_2026_13_05_22.json."""
        recording = Path(recording)
        return recording.with_name(f"config_{recording.stem}.json")

    def set_last(self, path):
        self.last_path = Path(path)
        self.file.setText(str(path))
        self.file.setToolTip(str(path))

    def update_controls(self, recording):
        """The last recording can be converted once its run has closed the file."""
        self.convert_last.setEnabled(self.last_path is not None and not recording and self.last_path.exists())

    def choose_and_convert(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Convert recording to MAT", self.folder.text(),
                                                "HDF5 recordings (*.h5 *.hdf5)")
        if path:
            self.convert(Path(path))

    def configure_mat_export(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("MAT export options")
        layout = W.QVBoxLayout(dialog)
        layout.addWidget(W.QLabel("Choose the HDF5 sections to include in the MATLAB file."))
        checks = {}
        labels = (("config", "Configuration"), ("results", "Decoded CS results"),
                  ("raw", "Raw wire frames"), ("events", "Session events"),
                  ("reports", "Reports"), ("log", "Client log"), ("host_log", "Host and peer log"),
                  ("context", "Pre-run context"))
        for key, label in labels:
            check = W.QCheckBox(label)
            check.setChecked(key in self.mat_options["include_groups"])
            checks[key] = check
            layout.addWidget(check)
        metadata = W.QCheckBox("Include metadata attributes")
        metadata.setChecked(self.mat_options["include_meta"])
        metadata.setToolTip("Format version, timestamps, firmware/protocol versions, CRCs and dataset annotations")
        layout.addWidget(metadata)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok |
                                     W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.mat_options = {"include_groups": {key for key, check in checks.items() if check.isChecked()},
                                "include_meta": metadata.isChecked()}

    def convert(self, source, options=None):
        output = Path(source).with_suffix(".mat")
        if output.exists():
            if W.QMessageBox.question(self, "Replace MAT file?", f"{output.name} already exists. Replace it?") \
                    != W.QMessageBox.StandardButton.Yes:
                return None
            output.unlink()
        try:
            from ..h5_to_mat import convert
            W.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                output = convert(source, output, **(self.mat_options if options is None else options))
            finally:
                W.QApplication.restoreOverrideCursor()
        except (ImportError, OSError, ValueError) as error:
            W.QMessageBox.warning(self, "Cannot convert recording", str(error))
            return None
        self.converted.emit(str(output))
        return output
