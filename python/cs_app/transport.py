"""Byte transports. Decoding and command sequencing belong to ClientSession."""
from threading import Lock
import time
from PyQt6 import QtCore


class LoopbackTransport:
    def __init__(self):
        self.is_open = False
        self.on_data = lambda data: None
        self.on_error = lambda error: None
        self.peer = lambda data: None
        self.on_close = lambda: None  # the peer sees the port close

    def open(self):
        self.is_open = True

    def close(self):
        was_open, self.is_open = self.is_open, False
        if was_open:
            self.on_close()

    def write(self, data):
        if not self.is_open:
            raise OSError("Transport closed")
        self.peer(bytes(data))

    def deliver(self, data):
        if self.is_open:
            self.on_data(bytes(data))


class SerialTransport(QtCore.QObject):
    received = QtCore.pyqtSignal(bytes, float)  # data, time.monotonic() at read
    failed = QtCore.pyqtSignal(str)

    class Reader(QtCore.QThread):
        def __init__(self, owner):
            super().__init__(owner)
            self.owner = owner

        def run(self):
            try:
                while not self.isInterruptionRequested():
                    data = self.owner.link.read(4096)
                    if data:
                        # Stamp on the reader thread: GUI latency must not shift recorded times.
                        self.owner.received.emit(data, time.monotonic())
            except Exception as error:
                if not self.isInterruptionRequested():
                    self.owner.failed.emit(str(error))

    def __init__(self, port, baud=921600, parent=None):
        super().__init__(parent)
        self.port, self.baud = port, baud
        self.lock = Lock()
        self.link = None
        self.reader = None
        self.on_data = lambda data: None
        self.on_error = lambda error: None
        self.received.connect(lambda data, received_at: self.on_data(data, received_at))
        self.failed.connect(lambda error: self.on_error(error))

    def open(self):
        import serial
        self.link = serial.Serial(self.port, self.baud, timeout=.1, write_timeout=2)
        self.link.reset_input_buffer()
        self.reader = self.Reader(self)
        self.reader.start()

    def write(self, data):
        with self.lock:
            if self.link is None or self.link.write(data) != len(data):
                raise OSError("Incomplete serial write")

    def close(self):
        if self.reader:
            self.reader.requestInterruption()
            self.reader.wait(1500)
        if self.link:
            self.link.close()
        self.link = None
