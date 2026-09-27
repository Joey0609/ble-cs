"""Qt signal facade; session callbacks always run on the GUI thread."""
from PyQt6 import QtCore
from .session import ClientSession


class QtSession(QtCore.QObject):
    session_started = QtCore.pyqtSignal(object)
    state_changed = QtCore.pyqtSignal(object)
    link_state_changed = QtCore.pyqtSignal(object)
    sync_changed = QtCore.pyqtSignal(object)
    command_result = QtCore.pyqtSignal(object)
    client_info = QtCore.pyqtSignal(object)
    client_state = QtCore.pyqtSignal(object)
    packet_received = QtCore.pyqtSignal(object)
    packet_sent = QtCore.pyqtSignal(object)
    config_received = QtCore.pyqtSignal(object)
    run_started = QtCore.pyqtSignal(object)
    run_finished = QtCore.pyqtSignal(object)
    procedures_complete = QtCore.pyqtSignal(object)
    peer_data = QtCore.pyqtSignal(object)
    connection_parameters = QtCore.pyqtSignal(object)
    attached_to_run = QtCore.pyqtSignal(object)
    link_error = QtCore.pyqtSignal(object)
    sync_failed = QtCore.pyqtSignal(object)
    start_failed = QtCore.pyqtSignal(object)
    recording_discarded = QtCore.pyqtSignal(object)
    history_started = QtCore.pyqtSignal(object)
    history_error = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.core = ClientSession(emit=lambda event, value: getattr(self, event).emit(value))
        self.timer = QtCore.QTimer(self, interval=50)
        self.timer.timeout.connect(self.core.tick)
        self.timer.start()
