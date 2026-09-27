from PyQt6 import QtWidgets as W
from ..config_sync import field_diff


class SyncDialog(W.QDialog):
    def __init__(self, host, client=None, parent=None, *, client_empty=False):
        super().__init__(parent)
        self.setWindowTitle("Synchronise configuration")
        self.action = None
        layout = W.QVBoxLayout(self)
        # A client without a configuration (e.g. after a reset) has nothing to get.
        text = ("The client holds no configuration. Apply the host configuration?" if client_empty else
                "The host and client configurations differ. Choose which configuration to use.")
        if host and client:
            text += "\n" + "\n".join(f"{key}: host {a!r} → client {b!r}" for key, (a, b) in field_diff(host, client).items())
        info = W.QPlainTextEdit(text)
        info.setReadOnly(True)
        layout.addWidget(info)
        actions = (("Get configuration from client", "get"),
                   ("Apply host configuration to client", "apply"), ("Cancel", "cancel"))
        for label, action in actions[client_empty:]:
            button = W.QPushButton(label)
            button.clicked.connect(lambda checked=False, action=action: self.choose(action))
            layout.addWidget(button)

    def choose(self, action):
        self.action = action
        self.accept()
