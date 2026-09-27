import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from PyQt6 import QtWidgets as W
import h5py
from cs_app.app import MainWindow
from cs_app.protocol.packets import DeviceNamePacket, OperationMode, decode_packet
from cs_app.protocol.config import ClientConfig
from cs_app.protocol.frame import Frame, ProtocolError
from cs_app.planner.export_c import document, load_document, generate
from cs_app.views.sync_dialog import SyncDialog
from cs_app.recorder import RunRecorder


class DeviceNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_encoding_and_validation(self):
        for name in ('Board 1', 'å' * 16):
            packet = DeviceNamePacket.from_name(name)
            self.assertEqual(len(packet.to_bytes()), 45)
            self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
            self.assertEqual(packet.text(), name)
        for name in ('', 'a' * 33, 'å' * 17, 'bad\0name', '\ud800'):
            with self.assertRaises(ValueError):
                DeviceNamePacket.from_name(name)
        with self.assertRaises(ProtocolError):
            DeviceNamePacket(1, b'a' * 32)
        with self.assertRaises(ProtocolError):
            DeviceNamePacket(1, b'\xff' + b'\0' * 31)

    def test_general_apply_fetch_save_record_and_default(self):
        window = MainWindow(simulate=True)
        try:
            field = window.general_view.device_name
            baseline = window.collect_config()
            field.setText('Lab board å')
            named = window.collect_config()
            self.assertNotEqual(named.crc32(), baseline.crc32())
            self.assertEqual(ClientConfig.from_packets(named.packets()), named)
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertEqual(window.simulator.config.device_name.text(), 'Lab board å')
            field.setText('Unsaved')
            window.session.fetch_config()
            self.assertEqual(field.text(), 'Lab board å')
            self.assertTrue(window.session.in_sync)
            source = generate(window.cs_view.scenario, window.cs_view.host_settings, role="initiator")["initiator"]
            self.assertIn("cs_generated_config_device_name", source)
            self.assertIn(f"0x{named.crc32():08x}U", source)
            self.assertEqual(load_document(source)[1]["device_name"], 'Lab board å')
            text = document(window.cs_view.scenario, window.cs_view.host_settings)
            scenario, host = load_document(text)
            field.setText('Changed')
            window.cs_view.host_settings = host
            window.cs_view.apply_config(scenario)
            self.assertEqual(field.text(), 'Lab board å')
            field.setText('å' * 17)
            self.assertIsNone(window.session.host_config)
            with tempfile.TemporaryDirectory() as directory:
                recorder = RunRecorder(Path(directory) / 'name.h5', config=named)
                recorder.close()
                with h5py.File(recorder.path) as file:
                    self.assertEqual(file['config/device_name'].asstr()[()], 'Lab board å')
            field.setText('Lab board å')
            window.select_role(OperationMode.RADIO_TX_TEST)
            self.assertFalse(field.isEnabled())
            self.assertIsNone(window.collect_config().device_name)
            window.select_role(OperationMode.CS_INITIATOR)
            self.assertEqual(field.text(), 'Lab board å')
            field.setText('')
            window.session.apply()
            self.assertIsNone(window.simulator.config.device_name)
            self.assertEqual(window.collect_config().crc32(), baseline.crc32())
        finally:
            window.close()
