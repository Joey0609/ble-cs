import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
from scipy.io import loadmat
from PyQt6 import QtWidgets as W

from ble_channel_sounding.protocol.packets import (RadioTestStatsPacket as Stats, PacketType, RadioTestType,
                                    OperationMode, decode_packet, packet_from_dict, packet_to_dict)
from ble_channel_sounding.protocol.frame import Frame, ProtocolError
from ble_channel_sounding.protocol.receiver import PacketReceiver
from ble_channel_sounding.radio_results import RadioResultStore
from ble_channel_sounding.protocol.config import ClientConfig
from ble_channel_sounding.recorder import RunRecorder, load
from ble_channel_sounding.h5_to_mat import convert
from ble_channel_sounding.views.radio_test_view import DEFAULT
from ble_channel_sounding.views.radio_results_view import RadioResultsWidget
from ble_channel_sounding.app import MainWindow
from ble_channel_sounding.views.sync_dialog import SyncDialog


FUTURE_RADIO_TEST = "Future: Radio Test is disabled in the desktop app while its firmware is work in progress"


class RadioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_wire_and_fragmented_receive(self):
        packet = Stats(0xffffffff, 3, -72, 80)
        self.assertEqual(packet.to_frame().payload, bytes.fromhex('ffffffff03000000b850'))
        self.assertEqual(len(packet.to_bytes()), 22)
        receiver = PacketReceiver()
        self.assertEqual(receiver.feed(packet.to_bytes()[:9]), [])
        self.assertEqual(receiver.feed(packet.to_bytes()[9:]), [packet])
        self.assertEqual(packet_from_dict('radio-test-stats', dict(packets_received=4, crc_errors=2, rssi_dbm=127, channel=0)), Stats(4, 2, 127, 0))
        self.assertEqual(packet_to_dict(packet)['packet_name'], 'radio_test_stats')
        with self.assertRaises(ProtocolError):
            decode_packet(Frame(PacketType.RADIO_TEST_STATS, b'\0' * 9))

    def test_rates_loss_unknown_rollover_reset_and_bound(self):
        store = RadioResultStore(max_samples=3)
        first = store.add(Stats(10, 0, 127, 1), 0)
        self.assertTrue(math.isnan(first.rssi))
        self.assertTrue(math.isnan(first.received_rate))
        sample = store.add(Stats(26, 2, -55, 2), 1)
        self.assertEqual(sample.received_rate, 16)
        self.assertAlmostEqual(sample.crc_percent, 100 * 2 / 18)
        self.assertEqual(sample.estimated_missing_rate(20), 2)
        self.assertTrue(math.isnan(sample.estimated_missing_rate(0)))
        self.assertEqual(sample.estimated_missing_rate(10), 0)
        self.assertTrue(store.add(Stats(0, 0, -50, 0), 2).reset)
        store.add(Stats(2, 0, -50, 0), 3)
        self.assertEqual(len(store.samples), 3)
        store.clear()
        store.add(Stats(0xfffffffe, 0xffffffff, -50, 0), 4)
        sample = store.add(Stats(2, 1, -50, 0), 5)
        self.assertEqual((sample.received_rate, sample.crc_rate), (4, 2))
        self.assertFalse(sample.reset)
        self.assertTrue(math.isnan(store.add(Stats(3, 1, -50, 0), 5).received_rate))
        self.assertEqual(store.add(Stats(6, 1, -50, 0), 6).received_rate, 4)

    def test_recording_replay_mat_and_view(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'radio.h5'
            config = ClientConfig(OperationMode.RADIO_TX_TEST, replace(DEFAULT, test_type=RadioTestType.RX))
            recorder = RunRecorder(path, config=config, clock=lambda: 100.)
            packets = [Stats(0, 0, 127, 0), Stats(18, 1, -60, 0)]
            for i, packet in enumerate(packets):
                recorder.record(packet, received_at=100 + i)
            recorder.close()
            self.assertEqual(load(path), packets)
            with h5py.File(path) as file:
                rows = file['radio_test/stats'][:]
                self.assertEqual(list(rows['t_host']), [0, 1])
                self.assertEqual(rows['rssi_dbm'][1], -60)
            mat = loadmat(convert(path), simplify_cells=True)
            self.assertEqual(list(mat['radio_test']['stats']['packets_received']), [0, 18])
            view = RadioResultsWidget()
            try:
                view.expected_rate.setValue(20)
                view.load_recording(path)
                self.assertEqual(list(view.curves['received_rate'].getData()[1])[1], 18)
                self.assertEqual(list(view.curves['missing'].getData()[1])[1], 1)
                self.assertIn('CRC failures: 1', view.summary.text())
            finally:
                view.close()

    def test_capture_actions_left_the_view_for_the_session_toolbar(self):
        view = RadioResultsWidget()
        try:
            self.assertFalse(view.findChildren(W.QPushButton))
            self.assertFalse(view.running)
            view.set_running(True)
            self.assertTrue(view.running)
            view.set_running(False)
            self.assertFalse(view.running)
            self.assertEqual(view.store.samples.maxlen, 5000)
        finally:
            view.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_simulated_rx_completion_and_second_run(self):
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.select_role(OperationMode.RADIO_TX_TEST)
                window.radio_view.apply_config(replace(DEFAULT, test_type=RadioTestType.RX, packet_count=40))
                window.recording_view.folder.setText(directory)
                window.recording_view.logging.setChecked(True)
                with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                    window.connect_port('Simulator', 921600)
                    self.app.processEvents()
                for run in range(2):
                    window.start()
                    for _ in range(5):
                        window.simulator.next_report = 0
                        window.simulator.tick()
                    self.assertEqual(window.radio_results.store.samples[-1].received, 40)
                    self.assertLessEqual(len(window.radio_results.store.samples), 4)
                    self.assertIsNone(window.session.recorder)
                files = list(Path(directory).glob('*.h5'))
                self.assertEqual(len(files), 2)
                with h5py.File(files[-1]) as file:
                    self.assertEqual(file['radio_test/stats'][-1]['packets_received'], 40)
        finally:
            window.close()

    def test_rx_sweep_continues_with_inactive_packet_count_and_stop_stats(self):
        from ble_channel_sounding.simulator import Simulator
        from ble_channel_sounding.session import ClientSession
        session = ClientSession()
        sim = Simulator(clock=lambda: 0)
        session.set_host_config(ClientConfig(OperationMode.RADIO_TX_TEST,
            replace(DEFAULT, test_type=RadioTestType.RX_SWEEP, packet_count=1,
                    sweep_start_channel=2, sweep_end_channel=4, sweep_delay_ms=200)))
        session.connect(sim.transport)
        session.apply()
        session.start()
        channels = [sim.radio_last.channel]
        for _ in range(3):
            sim.next_report = 0
            sim.tick()
            channels.append(sim.radio_last.channel)
        self.assertEqual(channels, [2, 3, 4, 2])
        self.assertTrue(session.running)
        session.stop()
        self.assertFalse(session.running)
        session.close()
