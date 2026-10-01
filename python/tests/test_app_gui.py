import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
import json
import logging
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PyQt6 import QtWidgets as W
from PyQt6.QtTest import QTest
from ble_channel_sounding.app import MainWindow, _RunDescriptionDialog
from ble_channel_sounding.recorder import RunRecorder, read_description
from ble_channel_sounding.views.sync_dialog import SyncDialog
from ble_channel_sounding.views.radio_test_view import (FEM_RAMP_UP_VALUES, TX_POWER_VALUES, UINT32_MAX,
                                          RadioTestView, _SpectrumPreview, DEFAULT)
from ble_channel_sounding.views.cs_view import PlannerWidget
from ble_channel_sounding.protocol.packets import (CsFaeTablePacket, LogMessagePacket, OperationMode,
                                     RadioTestPattern, RadioTestType)
from ble_channel_sounding.controller import INFO, compare_procedure
from ble_channel_sounding.session_history import SessionHistory
from ble_channel_sounding.views.fae_panel import FaePanel


# Behaviour the build no longer offers; these tests return when the capability does.
FUTURE_RADIO_TEST = "Future: Radio Test is disabled in the desktop app while its firmware is work in progress"
FUTURE_REFLECTOR_ROLE = "Future: the integrated client supports only the CS initiator role"


class AppGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_connected_board_antenna_count(self):
        for count in (1, 2, 4):
            with self.subTest(count=count):
                window = MainWindow(simulate=True)
                try:
                    from ble_channel_sounding.simulator import Simulator
                    simulator = Simulator(num_antennas_supported=count)
                    with patch.object(window, 'resolve_sync'):
                        window.session.connect(simulator.transport)
                        self.app.processEvents()
                    self.assertEqual(window.session.info.num_antennas_supported, count)
                    noun = 'antenna' if count == 1 else 'antennas'
                    self.assertIn(f'Connected board supports {count} {noun}',
                                  window.port_status.text())
                finally:
                    window.close()

    def test_fae_view_explains_fae_less_ipt_operation(self):
        panel = FaePanel()
        try:
            panel.observe_capabilities(SimpleNamespace(source=1, cs_without_fae_supported=1))
            panel.observe_configuration(SimpleNamespace(cs_enhancements_1=1))
            self.assertIn("No remote FAE table expected", panel.info.text())
            self.assertIn("FAE-less CS", panel.info.text())
            self.assertIn("IPT is enabled", panel.info.text())
        finally:
            panel.deleteLater()

    def test_unsupported_antenna_apply_shows_reason_alert(self):
        window = MainWindow(simulate=True)
        try:
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            antennas = window.cs_view.controls['procedure.tone_antenna_config_selection']
            antennas.setCurrentIndex(antennas.findData(1))  # A2:B1 on a one-antenna client
            window.cs_view.flush_edits()
            with patch.object(W.QMessageBox, 'warning') as warning:
                window.apply()
            warning.assert_called_once()
            self.assertEqual(warning.call_args.args[1], 'Configuration synchronisation refused')
            self.assertIn('Antenna configuration A2:B1 needs 2 initiator antennas',
                          warning.call_args.args[2])
            self.assertIn('client has 1 antenna', window.port_status.text())
        finally:
            window.close()

    def test_cs_setup_gap_role_controls_scan_options(self):
        window = MainWindow(simulate=True)
        try:
            general, peers, host = window.general_view, window.peers_view, window.cs_view.host_form
            self.assertTrue(host.isRowVisible(window.cs_view.host_controls['gap_role']))
            self.assertEqual(general.patterns.toPlainText(), 'CS')
            self.assertEqual(window.cs_view.patterns.toPlainText(), 'CS')
            self.assertFalse(peers.scan.isHidden())
            self.assertTrue(peers.advertise.isHidden())
            general.gap_role.setCurrentIndex(general.gap_role.findData(1))
            self.assertEqual(window.cs_view.host_settings['gap_role'], 1)
            self.assertEqual(window.session.host_config.config.gap_role, 1)
            self.assertIsNone(window.session.host_config.patterns)
            self.assertFalse(host.isRowVisible(window.cs_view.patterns))
            for widget in (peers.scan, peers.peers, peers.connect):
                self.assertTrue(widget.isHidden())
            self.assertFalse(peers.advertise.isHidden())
            general.gap_role.setCurrentIndex(general.gap_role.findData(0))
            general.patterns.setPlainText('Lab\nnRF')
            self.assertEqual(window.session.host_config.patterns.names(), ['Lab', 'nRF'])
            window.select_role(OperationMode.RADIO_TX_TEST)
            self.assertTrue(host.isRowVisible(window.cs_view.host_controls['gap_role']))
        finally:
            window.close()

    def test_simulator_sync_start_fae_results_stop_recording(self):
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.recording_view.folder.setText(directory)
                window.recording_view.logging.setChecked(True)
                with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                    window.connect_port('Simulator', 921600)
                    self.app.processEvents()
                window.scan_peers()
                window.connect_selected_peer()
                self.assertTrue(window.session.in_sync)
                window.start()
                self.assertFalse(window.recording_view.convert_last.isEnabled())
                window.update_controls()
                self.assertFalse(window.run_bar.buttons['Apply config'].isEnabled())
                self.assertFalse(window.general_view.isEnabled())
                # Sent settings lock; the example value panels stay editable.
                view = window.cs_view
                self.assertTrue(view.settings.isEnabled())
                for key in ("configuration.mode", "procedure.subevent_len", "connection.timeout"):
                    self.assertFalse(view.controls[key].isEnabled(), key)
                self.assertFalse(view.host_controls["max_tx_power"].isEnabled())
                for key in ("target_steps", "configuration.t_ip1_time_us", "connection.interval", "procedure.event_interval"):
                    self.assertTrue(view.controls[key].isEnabled(), key)
                self.assertFalse(view.controls["configuration.min_main_mode_steps"].isEnabled())
                self.assertFalse(window.cs_view.toolbar_buttons['Open…'].isEnabled())
                self.assertTrue(window.cs_view.views.isEnabled())
                with patch.object(W.QMessageBox, 'warning') as warning:
                    window.apply()
                warning.assert_called_once()
                self.assertEqual(window.session.state, 'RUNNING')
                configs = list(Path(directory).glob('config_*.json'))
                self.assertEqual(len(configs), 1)
                recording = window.recording_view.last_path
                self.assertEqual(configs[0].name, f'config_{recording.stem}.json')
                from ble_channel_sounding.planner.export_c import load_document
                from ble_channel_sounding.planner.bridge import config_packet
                scenario, host = load_document(configs[0].read_text())
                self.assertEqual(config_packet(scenario, host, OperationMode.CS_INITIATOR), window.session.host_config.config)
                window.simulator.tick()
                self.app.processEvents()
                # The remote FAE table is shown in the Controller view.
                self.assertEqual(window.controller_view.fae_table.ppm_per_lsb, 1/32)
                self.assertFalse(window.controller_view.fae_table.is_zero)
                self.assertTrue(window.results.store.procedures)
                self.assertTrue(next(iter(window.results.store.procedures.values())).reflector)
                controller = window.controller_view
                self.assertEqual(set(controller.reports.capabilities), {0, 1})
                self.assertEqual(controller.capabilities.horizontalHeaderItem(1).text(), "Local")
                self.assertGreater(controller.configuration.rowCount(), 0)
                self.assertGreater(controller.procedure.rowCount(), 0)
                self.assertIsNotNone(controller.requested)
                window.session.stop()
                self.assertIsNone(window.session.recorder)
                window.update_controls()
                self.assertTrue(window.run_bar.buttons['Apply config'].isEnabled())
                self.assertTrue(view.controls["configuration.mode"].isEnabled())
                self.assertTrue(view.host_controls["max_tx_power"].isEnabled())
                # Unlocking keeps the mode rules: no sub-mode, so the main run bounds stay read-only.
                self.assertFalse(view.controls["configuration.min_main_mode_steps"].isEnabled())
                files = list(Path(directory).glob('*.h5'))
                self.assertEqual(len(files), 1)
                self.assertRegex(files[0].name, r'^cs_initiator_\d{2}_[A-Z][a-z]{2}_\d{4}_\d{2}_\d{2}_\d{2}\.h5$')
                self.assertEqual(window.recording_view.file.text(), str(files[0]))
                window.update_controls()
                self.assertTrue(window.recording_view.convert_last.isEnabled())
                mat = window.recording_view.convert_last
                mat.click()
                self.assertTrue(files[0].with_suffix('.mat').exists())
                with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.StandardButton.No):
                    self.assertIsNone(window.recording_view.convert(files[0]))
                with patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(files[0]), '')), \
                        patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.StandardButton.Yes):
                    window.recording_view.convert_other.click()
                self.assertTrue(files[0].with_suffix('.mat').exists())
                # A failed FAE read keeps the table shown; the table goes with its link.
                before = window.controller_view.fae_table
                self.assertFalse(window.controller_view.set_fae_table(CsFaeTablePacket(1, 32)))
                self.assertIs(window.controller_view.fae_table, before)
                window.session.disconnect_link()
                self.app.processEvents()
                self.assertIsNone(window.controller_view.fae_table)
        finally:
            # The run left the non-modal run-description dialog open; a visible
            # dialog outlives this test and becomes the application's active
            # window, which breaks the hover tests that run later.
            if window._description_dialog is not None:
                window._description_dialog.close()
            window.close()

    def test_live_reports_keep_expansion_selection_and_disconnect_while_running(self):
        window = MainWindow(simulate=True)
        try:
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            window.scan_peers()
            window.connect_selected_peer()
            window.start()
            window.simulator.tick()
            window.results.refresh()
            results, model = window.results, window.session_view.model
            # The Session tab follows the live session: commands sent and frames received.
            self.assertEqual(window.tabs.tabText(window.tabs.indexOf(window.session_view)), "Session")
            self.assertEqual(window.session_view.source_label.text(), "Live session")
            directions = {model.data(model.index(row, 1)) for row in range(model.rowCount())}
            self.assertTrue({"Sent", "Received"} <= directions)
            capabilities = window.controller_view.capabilities
            capabilities.selectRow(1)
            count = model.rowCount()
            for packet in list(results.store.packets)[-3:]:
                results.add_packet(packet.packet)
                window.controller_view.add_packet(packet.packet)
                window.session.history.append(packet.packet, timestamp=1.0)
            window.session.history.flush()
            window.controller_view.refresh()
            results.refresh()
            self.assertGreater(model.rowCount(), count)
            self.assertEqual([i.row() for i in capabilities.selectionModel().selectedRows()], [1])
            buttons = window.run_bar.buttons
            window.update_controls()
            self.assertTrue(buttons['Connect'].isEnabled())
            self.assertEqual(window.run_bar.toolbar_actions['Connect peer'].text(), 'Disconnect peer')
            self.assertTrue(buttons['Connect peer'].isEnabled())
            with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.StandardButton.Yes):
                buttons['Connect peer'].click()
            self.app.processEvents()
            # The link ends and the client reconnects, ready to scan for another peer; the port stays open.
            self.assertEqual(window.session.state, 'CONFIGURED')
            self.assertIsNotNone(window.session.transport)
            self.assertTrue(window.simulator.connected)
            self.assertIn('link LINK_DISCONNECTED', window.state_label.text())
            self.assertEqual(window.run_bar.toolbar_actions['Connect peer'].text(), 'Connect peer')
            results.clear()
            self.assertEqual(window.session_view.source_label.text(), "No session yet: recent records")
        finally:
            window.close()

    def test_start_requires_synced_configuration(self):
        from ble_channel_sounding.protocol.packets import PacketType, StartPacket
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.recording_view.folder.setText(directory)
                window.recording_view.logging.setChecked(True)
                with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                    window.connect_port('Simulator', 921600)
                    self.app.processEvents()
                window.scan_peers()
                window.connect_selected_peer()
                length = window.cs_view.controls['procedure.subevent_len']
                length.setValue(length.value() + 1)
                window.cs_view.flush_edits()
                window.update_controls()
                self.assertFalse(window.run_bar.buttons['Start session'].isEnabled())
                with patch.object(window, 'show_alert') as alert:
                    window.start()
                alert.assert_called_once()
                self.assertIn('Synchronise', alert.call_args.args[1])
                self.assertNotEqual(window.session.state, 'RUNNING')
                self.assertEqual(list(Path(directory).iterdir()), [])
                length.setValue(length.value() - 1)
                window.cs_view.flush_edits()
                window.edited()
                self.assertTrue(window.session.in_sync)
                # The client confirms START but reports a configuration other than the host's.
                sim = window.simulator
                original = sim.handle
                def confirm_other(packet):
                    if packet.PACKET_TYPE == PacketType.START:
                        sim.config = replace(sim.config, config=replace(sim.config.config, max_tx_power=-9))
                        packet = StartPacket(sim.config.crc32())
                    original(packet)
                sim.handle = confirm_other
                with patch.object(W.QMessageBox, 'warning') as warning:
                    window.run_bar.buttons['Start session'].click()
                    self.app.processEvents()
                warning.assert_called_once()
                self.assertIn('not synced', warning.call_args.args[2])
                self.assertEqual(window.session.state, 'CONFIGURED')
                self.assertFalse(window.session.in_sync)
                self.assertEqual(list(Path(directory).iterdir()), [])
        finally:
            window.close()

    def test_reported_connection_parameters_reach_the_views(self):
        window = MainWindow(simulate=True)
        try:
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            window.scan_peers()
            window.connect_selected_peer()
            window.run_bar.buttons['Start session'].click()
            self.app.processEvents()
            requested = window.simulator.config.config
            table = window.controller_view.connection
            self.assertEqual(table.rowCount(), 4)
            self.assertEqual(table.item(0, 0).text(), 'Connection interval')
            self.assertEqual(table.item(0, 2).text(), f'{requested.connection_interval_min * 1.25:g} ms')
            self.assertEqual(table.item(0, 3).text(), '✓')
            self.assertEqual(table.item(3, 0).text(), 'ATT MTU')
            # The illustration credits the link instead of the requested range.
            info = window.cs_view.connection_info.text()
            self.assertIn('Interval reported by the client', info)
            self.assertNotIn('Requested interval', info)
            latency = window.cs_view.controls['connection.latency']
            latency.setValue(latency.value() + 1)
            window.cs_view.flush_edits()
            self.assertIn('Requested interval', window.cs_view.connection_info.text())
        finally:
            window.close()

    def test_failed_connect_marks_port_rejected(self):
        from ble_channel_sounding.views.port_view import PortView
        with patch('serial.tools.list_ports.comports', return_value=[]):
            view = PortView()
        view.port.addItem('/dev/cu.test — Test', '/dev/cu.test')
        view.mark_rejected('/dev/cu.test', 'CONNECT timeout')
        self.assertIn('rejected: CONNECT timeout', view.port.itemText(view.port.count() - 1))
        view.mark_rejected('/dev/cu.test', 'Connect rejected')
        self.assertEqual(view.port.itemText(view.port.count() - 1), '/dev/cu.test — Test — rejected: Connect rejected')
        view.clear_rejected('/dev/cu.test')
        self.assertEqual(view.port.itemText(view.port.count() - 1), '/dev/cu.test — Test')
        window = MainWindow(simulate=True)
        try:
            window.simulator.never_connect = True
            window.connect_port('Simulator', 921600)
            window.session.pending = (window.session.pending[0], 0)
            window.session.tick()
            self.assertEqual(window.port_view.rejected, {'Simulator': 'CONNECT timeout'})
        finally:
            window.close()

    def test_simulator_port_is_offered_without_flag(self):
        from ble_channel_sounding.views.port_view import SIMULATOR
        with patch('serial.tools.list_ports.comports', return_value=[]):
            window = MainWindow()
        try:
            self.assertIsNone(window.simulator)
            port = window.port_view.port
            port.setCurrentIndex(port.findData(SIMULATOR))
            window.port_view.refresh()
            self.assertEqual(port.currentData(), SIMULATOR)
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.port_view.connect_port()
                self.app.processEvents()
            self.assertIsNotNone(window.simulator)
            self.assertIs(window.session.transport, window.simulator.transport)
            self.assertTrue(window.session.in_sync)
        finally:
            window.close()

    def test_configuration_view_uses_toolbar_and_mode_specific_setup(self):
        from datetime import datetime
        from ble_channel_sounding.views.recording_view import recording_name
        window = MainWindow(simulate=True)
        try:
            buttons = window.run_bar.buttons
            self.assertTrue(buttons['Connect'].isEnabled())
            self.assertFalse(buttons['Apply config'].isEnabled())
            self.assertTrue(window.general_view.isEnabled())
            self.assertEqual(window.cs_view.settings.tabText(0), 'CS setup')
            self.assertIs(window.general_view.mode.parentWidget(), window.general_toolbar)
            self.assertIs(window.general_view.log_controls['console'].parentWidget(), window.general_toolbar)
            self.assertIs(window.general_view.log_controls['host'].parentWidget(), window.general_toolbar)
            self.assertIs(window.cs_view.cs_role.parentWidget(), window.cs_view.host_form.parentWidget())
            self.assertNotIn('Apply config', window.cs_view.toolbar_buttons)
            self.assertIs(window.config_stack.currentWidget(), window.configuration_host)
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertTrue(buttons['Connect'].isEnabled())
            self.assertIn('in sync', window.state_label.text())
            with patch.object(W.QFileDialog, 'getExistingDirectory', return_value='/tmp/chosen') as chooser:
                window.recording_view.browse()
            chooser.assert_called_once()
            self.assertEqual(window.recording_view.folder.text(), '/tmp/chosen')
            self.assertEqual(recording_name(OperationMode.RADIO_TX_TEST, datetime(2026, 9, 4, 7, 5, 3)),
                             'radio_tx_test_04_Sep_2026_07_05_03.h5')
            with tempfile.TemporaryDirectory() as directory:
                window.recording_view.folder.setText(directory)
                first = window.recording_view.path_for(OperationMode.CS_INITIATOR, datetime(2026, 9, 4, 7, 5, 3))
                first.touch()
                self.assertEqual(window.recording_view.path_for(OperationMode.CS_INITIATOR, datetime(2026, 9, 4, 7, 5, 3)).name,
                                 'cs_initiator_04_Sep_2026_07_05_03__2.h5')
        finally:
            window.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_radio_mode_and_reflector_role_select_their_setup(self):
        window = MainWindow(simulate=True)
        try:
            window.general_view.mode.setCurrentIndex(window.general_view.mode.findData(OperationMode.RADIO_TX_TEST))
            self.assertIs(window.config_stack.currentWidget(), window.radio_view)
            window.select_role(OperationMode.CS_REFLECTOR)
            self.assertEqual(window.general_view.mode.currentData(), OperationMode.CS_INITIATOR)
            self.assertEqual(window.cs_view.cs_role.currentData(), OperationMode.CS_REFLECTOR)
            self.assertIs(window.config_stack.currentWidget(), window.configuration_host)
        finally:
            window.close()

    @unittest.skip(FUTURE_REFLECTOR_ROLE)
    def test_received_configurations_keep_the_cs_role(self):
        window = MainWindow(simulate=True)
        try:
            view = window.cs_view
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            view.cs_role.setCurrentIndex(view.cs_role.findData(OperationMode.CS_REFLECTOR))
            view.flush_edits()
            window.apply()
            self.app.processEvents()
            # Scenarios and decoded packets carry the role as a plain int.
            window.config_received(window.session.client_config)
            self.assertEqual(view.cs_role.currentData(), OperationMode.CS_REFLECTOR)
            self.assertEqual(view.target_mode.currentData(), OperationMode.CS_REFLECTOR)
            view.apply_config(replace(view.scenario.configuration, role=1))
            self.assertEqual(view.cs_role.currentData(), OperationMode.CS_REFLECTOR)
            self.assertEqual(view.target_mode.count(), 2)
        finally:
            window.close()

    def test_hostless_mode_disables_client_log_controls(self):
        window = MainWindow(simulate=True)
        try:
            controls = window.general_view.log_controls
            self.assertTrue(all(control.isEnabled() for control in controls.values()))

            window.select_role(OperationMode.HOSTLESS_CS)
            self.assertTrue(all(not control.isEnabled() for control in controls.values()))

            window.select_role(OperationMode.CS_INITIATOR)
            self.assertTrue(all(control.isEnabled() for control in controls.values()))
        finally:
            window.close()

    def test_peer_link_toolbar_action_toggles_connect_and_disconnect_icons(self):
        window = MainWindow(simulate=True)
        try:
            button = window.run_bar.buttons["Connect"]
            self.assertEqual(button.toolTip(), "Connect client")
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertEqual(window.run_bar.toolbar_actions["Connect"].text(), "Disconnect client")
            self.assertEqual(button.toolTip(), "Disconnect client")
            self.assertTrue(button.isEnabled())
            actions = [action.text() for action in window.run_bar.actions() if not action.isSeparator()]
            self.assertLess(actions.index(window.run_bar.toolbar_actions['Connect'].text()),
                            actions.index('Apply config'))
            self.assertLess(actions.index('Synchronise'), actions.index('Scan'))
            self.assertLess(actions.index('Scan'), actions.index('Connect peer'))
            self.assertLess(actions.index('Connect peer'), actions.index('Start session'))
            self.assertLess(actions.index('Stop session'), actions.index('Record from now'))
            self.assertNotIn('Disconnect link', window.run_bar.buttons)

            peer_button = window.run_bar.buttons['Connect peer']
            self.assertTrue(peer_button.icon())
            window.scan_peers()
            window.connect_selected_peer()
            self.assertEqual(window.run_bar.toolbar_actions['Connect peer'].text(), 'Disconnect peer')
            self.assertTrue(window.run_bar.buttons['Start session'].isEnabled())

            # The same peer action drops the link and reconnects the client over the open port,
            # ready to scan for another peer.
            with patch.object(W.QMessageBox, 'question',
                              return_value=W.QMessageBox.StandardButton.Yes) as asked:
                peer_button.click()
                self.app.processEvents()
            self.assertIn('reconnect the client', asked.call_args[0][2])

            self.assertIn('link LINK_DISCONNECTED', window.state_label.text())
            self.assertEqual(window.session.state, "CONFIGURED")
            self.assertTrue(window.simulator.connected)
            self.assertIsNotNone(window.session.transport)
            self.assertEqual(window.run_bar.toolbar_actions["Connect"].text(), "Disconnect client")
            self.assertEqual(window.run_bar.toolbar_actions['Connect peer'].text(), 'Connect peer')
            self.assertTrue(button.isEnabled())
            self.assertFalse(window.port_view.isEnabled())  # the port is still ours
            window.scan_peers()
            window.connect_selected_peer()

            # Disconnect client ends the peer session but keeps the serial port open.
            button.click()
            self.app.processEvents()

            self.assertEqual(window.session.state, "DISCONNECTED")
            self.assertIn('link LINK_DISCONNECTED', window.state_label.text())
            self.assertIsNotNone(window.session.transport)
            self.assertFalse(window.simulator.connected)
            self.assertEqual(window.run_bar.toolbar_actions["Connect"].text(), "Connect client")
            self.assertTrue(button.isEnabled())
            self.assertFalse(window.port_view.isEnabled())
            window.session.close_port()
        finally:
            window.close()

    def test_connect_toolbar_cancels_an_unanswered_handshake(self):
        window = MainWindow(simulate=True)
        try:
            button = window.run_bar.buttons["Connect"]
            action = window.run_bar.toolbar_actions["Connect"]
            window.simulator.never_connect = True
            window.connect_port('Simulator', 921600)
            self.app.processEvents()
            self.assertEqual(window.session.state, "CONNECTING")
            self.assertEqual(action.text(), "Cancel connection")
            self.assertEqual(button.toolTip(), "Cancel connection")
            self.assertTrue(button.isEnabled())

            button.click()
            self.app.processEvents()

            # Cancelled before the CONNECT deadline: no failure, and the port is not marked rejected.
            self.assertEqual(window.session.state, "DISCONNECTED")
            self.assertIsNone(window.session.transport)
            self.assertEqual(window.port_view.rejected, {})
            self.assertIn("cancelled", window.port_status.text())
            self.assertEqual(action.text(), "Connect client")
            self.assertTrue(button.isEnabled())
            self.assertTrue(window.port_view.isEnabled())

            window.simulator.never_connect = False
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertEqual(action.text(), "Disconnect client")
        finally:
            window.close()

    def test_hostless_status_survives_failed_open_and_clears_rejection_on_success(self):
        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.HOSTLESS_CS)
            window.port_view.mark_rejected('Simulator', 'previous failure')
            window.connect_port('Simulator', 921600)
            self.app.processEvents()

            self.assertEqual(window.session.state, 'HOSTLESS CS')
            self.assertNotIn('rejected', window.port_view.port.currentText())
            self.assertEqual(window.port_status.text(), 'Hostless CS · receiving protocol frames')
        finally:
            window.close()

    def test_failed_hostless_open_does_not_report_receiving_status(self):
        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.HOSTLESS_CS)
            with patch('ble_channel_sounding.app.SerialTransport.open', side_effect=OSError('open failed')):
                window.connect_port('/dev/missing', 921600)

            self.assertEqual(window.session.state, 'FAILED')
            self.assertEqual(window.port_status.text(), 'open failed')
            self.assertNotIn('receiving', window.port_status.text())
        finally:
            window.close()

    def test_new_session_clears_transient_status_message(self):
        window = MainWindow(simulate=True)
        try:
            window.show_message('stale status', 10000)
            self.assertTrue(window.message_timer.isActive())
            window.clear_session_reports()

            self.assertEqual(window.port_status.text(), '')
            self.assertEqual(window.message_label.text(), '')
            self.assertFalse(window.message_timer.isActive())
        finally:
            window.close()

    def test_confirmed_start_drops_previous_session_error_from_status_bar(self):
        window = MainWindow(simulate=True)
        try:
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            client_status = window.port_status.text()
            self.assertIn('Firmware', client_status)
            window.scan_peers()
            window.connect_selected_peer()
            interruption = 'Client operation interrupted: ERROR, reason CS_CONFIG_FAILED, error -EIO (-5)'
            window.error(interruption)
            self.assertEqual(window.port_status.text(), interruption)
            self.assertEqual(window.message_label.text(), interruption)

            window.start()
            self.app.processEvents()

            self.assertEqual(window.session.state, 'RUNNING')
            self.assertEqual(window.port_status.text(), client_status)
            self.assertEqual(window.message_label.text(), '')
            window.session.stop()
            window._session_saved = True
        finally:
            window.close()

    def test_hostless_toggle_only_closes_the_port(self):
        """Hostless CS has no command channel, so the toggle closes the port (§7.8)."""
        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.HOSTLESS_CS)
            window.connect_port('Simulator', 921600)
            self.app.processEvents()
            button = window.run_bar.buttons['Connect']
            action = window.run_bar.toolbar_actions['Connect']
            self.assertEqual(window.session.state, 'HOSTLESS CS')
            self.assertEqual(action.text(), 'Disconnect client')
            self.assertTrue(button.isEnabled())

            button.click()
            self.app.processEvents()

            self.assertEqual(window.session.state, 'DISCONNECTED')
            self.assertIsNone(window.session.transport)
            self.assertFalse(window.session.hostless)
            self.assertEqual(action.text(), 'Connect client')
            self.assertTrue(button.isEnabled())
            self.assertTrue(window.port_view.isEnabled())
        finally:
            window.close()

    def test_peer_console_settings_round_trip_as_host_only_data(self):
        from ble_channel_sounding.planner.export_c import document, load_document
        window = MainWindow(simulate=True)
        try:
            self.assertEqual([window.serial_port_tabs.tabText(i) for i in range(window.serial_port_tabs.count())],
                             ['Client', 'Peer'])
            window.peer_console_view.port.setText('/dev/peer-console')
            window.peer_console_view.baud.setCurrentText('460800')
            self.assertEqual(window.cs_view.host_settings['peer_console'],
                             {'port': '/dev/peer-console', 'baud': 460800})
            _, host = load_document(document(window.cs_view.scenario, window.cs_view.host_settings))
            self.assertEqual(host['peer_console'], {'port': '/dev/peer-console', 'baud': 460800})
        finally:
            window.close()

    def test_peer_console_fake_serial_lifecycle_feeds_peer_history(self):
        class FakeSerialTransport:
            instances = []

            def __init__(self, port, baud, parent=None):
                self.port, self.baud = port, baud
                self.on_data = lambda data, timestamp=None: None
                self.on_error = lambda text: None
                self.opened = False
                self.closed = False
                self.instances.append(self)

            def open(self):
                self.opened = True

            def close(self):
                self.closed = True

        window = MainWindow(simulate=True)
        history = SessionHistory()
        try:
            window.session.history = history
            window.peer_console_view.port.setText('/dev/fake-peer')
            window.peer_console_view.baud.setCurrentText('460800')
            with patch('ble_channel_sounding.app.SerialTransport', FakeSerialTransport):
                window.peer_console_run_started('started')
                transport = FakeSerialTransport.instances[-1]
                self.assertTrue(transport.opened)
                self.assertTrue(window.peer_console_view.button.isChecked())
                transport.on_data(b'<wrn> peer failed\n', 12.0)
                window.close_peer_console()
                self.app.processEvents()
                history.flush()
            self.assertTrue(transport.closed)
            self.assertTrue(any(entry.kind == 'peer' and entry.source == 'peer'
                                for entry in history.entries))
        finally:
            history.close()
            window.session.history = None
            window.close()

    def test_peer_console_open_failure_is_a_host_warning(self):
        class FailingSerialTransport:
            def __init__(self, port, baud, parent=None):
                self.on_data = self.on_error = None

            def open(self):
                raise OSError("port busy")

            def close(self):
                pass

        window = MainWindow(simulate=True)
        history = SessionHistory()
        try:
            window.session.history = history
            with patch('ble_channel_sounding.app.SerialTransport', FailingSerialTransport):
                window.open_peer_console('/dev/fake-peer', 460800)
            history.flush()
            entry = [entry for entry in history.entries if entry.kind == 'host'][-1]
            self.assertEqual((entry.source, entry.level), ('host', 'wrn'))
            self.assertIn('port busy', history.read(entry).text)
            window._session_saved = True
        finally:
            history.close()
            window.session.history = None
            window.close()

    def test_cancelled_close_keeps_the_peer_console(self):
        window = MainWindow(simulate=True)
        closed = []
        try:
            window.close_peer_console = lambda: closed.append(True)

            class CancelBox:
                class Icon:
                    Question = None

                class ButtonRole:
                    AcceptRole = DestructiveRole = RejectRole = None

                def __init__(self, parent):
                    self.buttons = []

                def setIcon(self, icon):
                    pass

                def setWindowTitle(self, text):
                    pass

                def setText(self, text):
                    pass

                def addButton(self, text, role):
                    self.buttons.append(text)
                    return text

                def exec(self):
                    return 0

                def clickedButton(self):
                    return "Cancel"

            event = Mock()
            with patch.object(window, 'isVisible', return_value=True), \
                    patch.object(window, '_unsaved_session_prompt', return_value=True), \
                    patch('ble_channel_sounding.app.W.QMessageBox', CancelBox):
                window.closeEvent(event)
            event.ignore.assert_called_once()
            self.assertEqual(closed, [])
        finally:
            del window.close_peer_console
            window._session_saved = True
            window.close()

    def test_application_warning_is_marshaled_into_host_history(self):
        window = MainWindow(simulate=True)
        history = SessionHistory()
        try:
            window.session.history = history
            logging.getLogger('ble_channel_sounding.test').warning('background diagnostic')
            self.app.processEvents()
            history.flush()
            self.assertTrue(any(entry.kind == 'host' and entry.source == 'ble_channel_sounding.test'
                                for entry in history.entries))
            window._session_saved = True
        finally:
            history.close()
            window.session.history = None
            window.close()

    def test_run_description_dialog_writes_multiline_notes(self):
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'run.h5'
                recorder = RunRecorder(path, write_config=False, description='setup')
                recorder.close()
                dialog = _RunDescriptionDialog(path, 'setup', window)
                dialog.editor.setPlainText('completed\nremote peer disconnected')
                self.assertTrue(dialog.save_text())
                self.assertEqual(read_description(path), 'completed\nremote peer disconnected')
                dialog.close()
        finally:
            window.close()

    def test_describe_session_lives_in_the_session_toolbar(self):
        window = MainWindow(simulate=True)
        try:
            names = [action.text() for action in window.run_bar.actions() if not action.isSeparator()]
            self.assertEqual(names[names.index('Record from now') + 1], 'Describe session')
            self.assertFalse(hasattr(window.session_view, 'edit_description_button'))
            button = window.run_bar.buttons['Describe session']
            self.assertIn('Describe session', button.toolTip())
            window.update_controls()
            self.assertFalse(button.isEnabled())  # no session, no capture, no notes

            # Describing a running recording reaches the Session tab and, at Stop,
            # the closing Run description editor.
            self._started_run(window)
            window.update_controls()
            self.assertTrue(button.isEnabled())
            with patch.object(W.QInputDialog, 'getMultiLineText', return_value=('two peers\nindoors', True)):
                button.click()
            self.assertEqual(window.results.description_text, 'two peers\nindoors')
            self.assertEqual(window.session_view.description_label.toolTip(), 'two peers\nindoors')
            self.assertEqual(window.recording_view.description.text(), '')
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'run.h5'
                RunRecorder(path, write_config=False).close()
                window._active_recording_path = path
                window.run_finished('stopped')
                self.assertEqual(window._description_dialog.editor.toPlainText(), 'two peers\nindoors')
                window._description_dialog.close()
        finally:
            window.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_capture_actions_reach_the_radio_view_in_radio_mode(self):
        window = MainWindow(simulate=True)
        try:
            open_button = window.run_bar.buttons['Open capture…']
            clear_button = window.run_bar.buttons['Clear']
            window.select_role(OperationMode.RADIO_TX_TEST)
            with patch.object(window.radio_results, 'open_capture') as radio_open, \
                    patch.object(window.radio_results, 'clear') as radio_clear:
                open_button.click()
                clear_button.click()
            radio_open.assert_called_once_with()
            radio_clear.assert_called_once_with()
        finally:
            window.close()

    def test_capture_actions_live_in_the_session_toolbar(self):
        """Open capture… and Clear are record-management toolbar actions over the shown view."""
        window = MainWindow(simulate=True)
        try:
            names = [action.text() for action in window.run_bar.actions() if not action.isSeparator()]
            self.assertEqual(names[names.index('Describe session') + 1:],
                             ['Open capture…', 'Clear', 'Help'])
            self.assertNotIn('Close session', names)  # the teardown belongs to the toggle (§7.8)
            labels = {button.text() for button in window.results.findChildren(W.QPushButton)}
            self.assertFalse(labels & {'Open capture…', 'Clear'})
            open_button = window.run_bar.buttons['Open capture…']
            clear_button = window.run_bar.buttons['Clear']
            self.assertIn('recording or capture', open_button.toolTip())
            # Offline actions: no link needed, and locked once a run owns the views.
            window.update_controls()
            self.assertTrue(open_button.isEnabled())
            self.assertTrue(clear_button.isEnabled())

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'capture.h5'
                recorder = RunRecorder(path, write_config=False, description='indoors')
                recorder.record(LogMessagePacket(b'from the capture'))
                recorder.close()
                with patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
                    open_button.click()
                self.assertEqual(window.results.capture_path, path)
                clear_button.click()
                self.assertIsNone(window.results.capture_path)

            self._started_run(window)
            window.update_controls()
            self.assertFalse(open_button.isEnabled())
            self.assertFalse(clear_button.isEnabled())
        finally:
            window.close()

    def _started_run(self, window):
        with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
            window.connect_port('Simulator', 921600)
            self.app.processEvents()
        window.scan_peers()
        window.connect_selected_peer()
        window.start()
        window.simulator.tick()
        window.results.refresh()

    def test_save_session_defaults_to_recording_folder_and_keeps_planner_json(self):
        from PyQt6.QtCore import QThreadPool
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.recording_view.folder.setText(directory)
                self._started_run(window)
                window.update_controls()
                self.assertTrue(window.recording_view.save_session.isEnabled())
                self.assertTrue(window.session_view.save_session_button.isEnabled())
                default = Path(window.default_session_path())
                self.assertEqual(default.parent, Path(directory))
                self.assertTrue(default.name.startswith('session_cs_initiator_'))
                self.assertTrue(window.save_session(default, 'notes'))
                QThreadPool.globalInstance().waitForDone(10000)
                self.app.processEvents()
                self.assertTrue(default.exists())
                config = window.recording_view.config_path_for(default)
                self.assertEqual(json.loads(config.read_text())['host_settings']['peer_data'], 0)
                self.assertEqual(read_description(default), 'notes')
        finally:
            window._session_saved = True
            window.close()

    def test_save_session_offers_the_recording_that_holds_the_session(self):
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                self._started_run(window)
                recording = Path(directory) / 'run.h5'
                RunRecorder(recording, write_config=False).close()
                window.results.session_recording_path = recording
                with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.StandardButton.Open) as asked:
                    window.session_view.save_session()
                self.assertIn('run.h5 already holds it', asked.call_args[0][2])
                self.assertEqual(window.session_view.source_label.text(), 'Capture: run.h5')
                self.assertFalse(window.session_view.save_session_button.isEnabled())
        finally:
            window._session_saved = True
            window.close()

    def test_stopped_run_offers_the_save_once(self):
        """A stopped run offers the save that makes its session browsable (§7.9)."""
        window = MainWindow(simulate=True)
        try:
            self._started_run(window)
            # Only a user-visible window is offered the save; the harness keeps
            # its windows hidden, as the close prompt does.
            with patch.object(MainWindow, 'isVisible', return_value=True):
                with patch.object(W.QMessageBox, 'question',
                                  return_value=W.QMessageBox.StandardButton.Save) as asked, \
                        patch.object(window.session_view, 'save_session') as save:
                    window.run_finished('STOP confirmed')
                save.assert_called_once_with()
                self.assertIn('Save this session', asked.call_args[0][2])

                # A session already in a file is not offered again.
                window._session_saved = True
                with patch.object(W.QMessageBox, 'question') as asked_again:
                    window.run_finished('STOP confirmed')
                asked_again.assert_not_called()
        finally:
            # run_finished() also opens the non-modal run-description dialog;
            # leaving it active would make it the application's active window.
            if window._description_dialog is not None:
                window._description_dialog.close()
            window._session_saved = True
            window.close()

    def test_saved_session_is_browsed_in_replay(self):
        """After the save the app replays the file: browsing reads it, not the temporary history (§7.9)."""
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                self._started_run(window)
                self.assertFalse(window.results.recording_playback)
                window.session.stop()
                window.update_controls()
                path = Path(directory) / 'session.h5'
                window.session.history.save_hdf5(path, write_config=False)
                window.session_saved(str(path))

                self.assertTrue(path.exists())
                self.assertTrue(window.results.recording_playback)
                self.assertEqual(window.results.capture_path, path)
                self.assertEqual(window.session_view.source_label.text(), 'Capture: session.h5')
                # Browsing the saved session: its filters and its whole timeline.
                self.assertTrue(window.session_view.search.isEnabled())
                self.assertGreater(window.session_view.model.rowCount(), 0)
        finally:
            if window._description_dialog is not None:
                window._description_dialog.close()
            window._session_saved = True
            window.close()

    def test_history_limit_is_a_setting_for_the_next_session(self):
        window = MainWindow(simulate=True)
        try:
            self.assertEqual(window.session.history_kwargs['max_bytes'], 2 * 2**30)
            window.recording_view.history_limit.setValue(0.5)
            self.assertEqual(window.session.history_kwargs['max_bytes'], 2**29)
        finally:
            window.close()

    def test_host_messages_before_the_first_session_appear_in_the_session_tab(self):
        window = MainWindow(simulate=True)
        try:
            self.assertIsNone(window.session.history)
            window.show_message('Port busy', level='wrn')
            window.results.refresh()
            model = window.session_view.model
            rows = [(model.data(model.index(r, 1)), model.data(model.index(r, 2)), model.data(model.index(r, 4)))
                    for r in range(model.rowCount())]
            self.assertIn(('Host', 'Host · wrn', 'host: Port busy'), rows)
        finally:
            window.close()

    def test_unsaved_history_is_detected_for_visible_close_prompt(self):
        window = MainWindow(simulate=True)
        history = SessionHistory()
        try:
            history.append_host('info', 'host', 'unsaved')
            history.flush()
            window.session.history = history
            self.assertTrue(window._unsaved_session_prompt())
            window._session_recorded = True
            self.assertFalse(window._unsaved_session_prompt())
        finally:
            history.close()
            window.session.history = None
            window.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_configuration_workspace_and_toolbar_survive_radio_mode_switch(self):
        window = MainWindow(simulate=True)
        try:
            workspace = window.configuration_host
            toolbar = window.configuration_toolbar
            configuration_index = window.tabs.indexOf(window.config_stack)
            window.tabs.setCurrentIndex(configuration_index)
            window.select_role(OperationMode.RADIO_TX_TEST)
            self.assertIs(window.tabs.widget(configuration_index), window.config_stack)
            self.assertIs(window.configuration_host.centralWidget(), window.cs_view)
            self.assertIs(window.config_stack.currentWidget(), window.radio_view)
            self.assertIs(toolbar.parentWidget(), workspace)
            window.select_role(OperationMode.CS_INITIATOR)
            self.assertIs(window.config_stack.currentWidget(), workspace)
            self.assertIs(toolbar.parentWidget(), workspace)
        finally:
            window.close()

    def test_general_toolbar_and_cs_setup_do_not_leak_into_radio_view(self):
        window = MainWindow(simulate=True)
        try:
            self.assertEqual(window.general_view.mode.currentText(), "CS")
            self.assertEqual(window.cs_view.cs_role.currentText(), "Initiator")
            self.assertIsNotNone(window.cs_view.device_name)
            window.select_role(OperationMode.RADIO_TX_TEST)
            self.assertFalse(any(child.objectName() == "device_name"
                                 for child in window.radio_view.findChildren(W.QWidget)))
            self.assertIs(window.general_view.mode.parentWidget(), window.general_toolbar)
        finally:
            window.close()

    def test_empty_client_is_only_offered_apply(self):
        texts = lambda dialog: [b.text() for b in dialog.findChildren(W.QPushButton)]
        self.assertIn('Get configuration from client', texts(SyncDialog(None)))
        self.assertNotIn('Get configuration from client', texts(SyncDialog(None, client_empty=True)))

    def test_widgets_and_radio_preserve_inactive_values(self):
        from ble_channel_sounding.views.results_view import ResultsWidget
        for cls in (PlannerWidget, ResultsWidget):
            widget = cls()
            self.assertIsInstance(widget, W.QWidget)
            self.assertNotIsInstance(widget, W.QMainWindow)
            widget.close()
        view = RadioTestView()
        view.controls['packet_count'].setText(str(2**32 - 1))
        self.assertEqual(view.collect_config().packet_count, 2**32 - 1)
        test_type = view.controls['test_type']
        self.assertIsInstance(test_type, W.QComboBox)
        test_type.setCurrentIndex(test_type.findData(int(RadioTestType.TX_SWEEP)))
        self.assertFalse(view.controls['channel'].isEnabled())
        self.assertEqual(view.collect_config().channel, DEFAULT.channel)
        self.assertEqual(view.collect_config().test_type, RadioTestType.TX_SWEEP)
        unknown = replace(DEFAULT, phy=9)
        view.apply_config(unknown)
        self.assertEqual(view.controls['phy'].currentText(), 'Unknown (9)')
        with self.assertRaises(ValueError):
            view.collect_config()
        view.close()

    def test_radio_view_groups_active_fields_and_reports_invalid_edits(self):
        view = RadioTestView()
        try:
            groups = {box.title() for box in view.findChildren(W.QGroupBox) if box is not view.preview}
            self.assertEqual(groups, set())
            self.assertEqual([view.tabs.tabText(i) for i in range(view.tabs.count())],
                             ["Test", "Channel", "Timing", "FEM"])
            self.assertEqual([view.help_pane.tabText(i) for i in range(view.help_pane.count())],
                             ["About this tab", "Setting details"])
            self.assertIn("Select the radio test operation", view.tab_help.toPlainText())
            view.show_setting_help("test_type")
            self.assertIn("What it defines", view.setting_help.toPlainText())
            self.assertIn("radio operation", view.setting_help.toPlainText())
            self.assertEqual(view.labels["channel"].text(), "Channel")
            self.assertIn("BLE and Nordic", view.controls["channel"].toolTip())
            self.assertTrue(view.controls["channel"].isEnabled())
            self.assertTrue(view.controls["txpower"].isEnabled())
            self.assertIsInstance(view.controls["channel"], W.QSpinBox)
            for name in ("txpower", "fem_ramp_up_time_us"):
                self.assertIsInstance(view.controls[name], W.QComboBox)
            self.assertIsInstance(view.controls["sweep_delay_ms"], W.QDoubleSpinBox)
            self.assertEqual(view.controls["sweep_delay_ms"].minimum(), 1.0)
            self.assertEqual(view.controls["sweep_delay_ms"].maximum(), UINT32_MAX)
            self.assertEqual(view.controls["channel"].minimum(), 0)
            self.assertEqual(view.controls["channel"].maximum(), 80)
            view.controls["phy"].setCurrentIndex(view.controls["phy"].findData(6))
            self.assertEqual(view.controls["channel"].minimum(), 11)
            self.assertEqual(view.controls["channel"].maximum(), 26)
            self.assertEqual({view.controls["txpower"].itemData(i)
                              for i in range(view.controls["txpower"].count())}, set(TX_POWER_VALUES))
            self.assertEqual({view.controls["fem_ramp_up_time_us"].itemData(i)
                              for i in range(view.controls["fem_ramp_up_time_us"].count())},
                             set(FEM_RAMP_UP_VALUES))
            pattern_values = {view.controls["pattern"].itemData(i)
                              for i in range(view.controls["pattern"].count())}
            self.assertEqual(pattern_values, set(RadioTestPattern))
            self.assertFalse(view.controls["packet_count"].isEnabled())
            self.assertFalse(view.controls["sweep_start_channel"].isEnabled())

            view.controls["test_type"].setCurrentIndex(
                view.controls["test_type"].findData(int(RadioTestType.RX_SWEEP)))
            self.assertFalse(view.controls["txpower"].isEnabled())
            self.assertTrue(view.controls["sweep_start_channel"].isEnabled())
            self.assertTrue(view.controls["sweep_end_channel"].isEnabled())
            self.assertFalse(view.controls["channel"].isEnabled())
            self.assertIn("Ready", view.status.text())
            self.assertEqual(view.preview.title_label.text(), "RX sweep")

            view.controls["duty_cycle"].setText("bad")
            self.assertIn("invalid", view.status.text().lower())
            with self.assertRaises(ValueError):
                view.collect_config()
        finally:
            view.close()

    def test_radio_preview_draws_rf_view_and_main_splitter_is_resizable(self):
        view = RadioTestView()
        try:
            spectrum = view.preview.spectrum
            self.assertEqual(spectrum.frequencies, (2403.0,))
            self.assertEqual(spectrum.center_frequency_mhz, 2403.0)
            self.assertEqual(spectrum.channel_spacing_mhz, 1.0)
            self.assertIn("centre spacing: 1 MHz", view.preview.parameters.text())
            self.assertEqual(view.main_splitter.count(), 2)
            self.assertEqual(view.main_splitter.handleWidth(), 8)
            self.assertIn("not a live spectrum", view.preview.note.text().lower())

            view.apply_config(replace(DEFAULT, test_type=RadioTestType.MODULATED_TX,
                                      pattern=RadioTestPattern.PATTERN_00000000))
            self.assertEqual(spectrum.example_frame, b"\x00" * 32)
            zero_level = _SpectrumPreview._gfsk_waveform(RadioTestPattern.PATTERN_00000000, 1.0)[1]
            random_level = _SpectrumPreview._gfsk_waveform(RadioTestPattern.RANDOM, 1.0)[1]
            self.assertNotEqual(zero_level.tolist(), random_level.tolist())

            view.apply_config(replace(DEFAULT, phy=6, channel=11))
            self.assertEqual(spectrum.frequencies, (2405.0,))
            self.assertEqual(spectrum.channel_spacing_mhz, 5.0)

            view.apply_config(replace(DEFAULT, test_type=RadioTestType.TX_SWEEP,
                                      sweep_start_channel=10, sweep_end_channel=12))
            self.assertEqual(spectrum.channels, (10, 11, 12))
            self.assertEqual(spectrum.frequencies, (2410.0, 2411.0, 2412.0))
            self.assertEqual(spectrum.center_frequency_mhz, None)

            view.resize(1200, 700)
            view.show()
            self.app.processEvents()
            self.assertFalse(spectrum.grab().isNull())
        finally:
            view.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_radio_preset_round_trip_and_running_lock(self):
        from ble_channel_sounding.views.radio_test_view import preset_json
        view = RadioTestView()
        try:
            original = view.collect_config()
            view.set_log({"console": 4, "host": 1})
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "radio.json"
                source.write_text(preset_json(original, view.log), encoding="utf-8")
                with patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
                    view.open_file()
                self.assertEqual(view.collect_config(), original)
                self.assertEqual(view.log, {"console": 4, "host": 1})
                target = Path(directory) / "saved.json"
                with patch.object(W.QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                    view.save_file()
                saved = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(saved["log"], {"console": 4, "host": 1})
                self.assertEqual(saved["packet_count"], original.packet_count)
        finally:
            view.close()

        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.RADIO_TX_TEST)
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertTrue(window.session.in_sync)
            window.start()
            window.update_controls()
            self.assertFalse(window.radio_view.isEnabled())
            window.session.stop()
            window.update_controls()
            self.assertTrue(window.radio_view.isEnabled())
            # The close-prompt behavior is covered separately; this UI lock test does not
            # need to interact with a modal prompt in the offscreen test process.
            window._session_saved = True
        finally:
            window.close()

    def test_results_mode_applies_on_confirmed_run_start(self):
        window = MainWindow(simulate=True)
        try:
            results, mode = window.results, window.cs_view.controls["configuration.mode"]
            mode.setCurrentIndex(mode.findData(1))
            window.cs_view.flush_edits()
            self.assertIsNone(results.measurement_mode)
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            self.assertIsNone(results.measurement_mode)
            window.scan_peers()
            window.connect_selected_peer()
            window.start()
            self.assertEqual(results.measurement_mode, 1)
            window.session.stop()
            mode.setCurrentIndex(mode.findData(2))
            window.cs_view.flush_edits()
            self.assertEqual(results.measurement_mode, 1)
        finally:
            window.close()

    def test_hostless_negotiated_configuration_applies_results_mode(self):
        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.HOSTLESS_CS)
            self.assertIsNone(window.results.measurement_mode)

            negotiated = replace(window.cs_view.scenario.configuration, mode=1)
            window.cs_packet_received(negotiated)

            self.assertEqual(window.results.measurement_mode, 1)
            self.assertFalse(window.results.tabs.isTabVisible(window.results.tabs.indexOf(window.results.pbr_page)))
            self.assertTrue(window.results.tabs.isTabVisible(window.results.tabs.indexOf(window.results.rtt_page)))
        finally:
            window.close()

    def test_hostless_mode_drops_the_requested_configuration(self):
        """Selecting hostless CS clears the request the previous mode left behind."""
        window = MainWindow(simulate=True)
        try:
            self.assertIsNotNone(window.controller_view.requested)
            window.select_role(OperationMode.HOSTLESS_CS)
            self.assertIsNone(window.controller_view.requested)
        finally:
            window.close()

    def test_hostless_replay_keeps_its_mode_and_compares_nothing(self):
        """A hostless capture reports a negotiated role, not a request."""
        window = MainWindow(simulate=True)
        try:
            window.select_role(OperationMode.HOSTLESS_CS)
            negotiated = replace(window.cs_view.scenario.configuration, role=0)
            procedure = replace(window.cs_view.scenario.procedure, subevent_len=20000,
                                procedure_interval=2)
            window.controller_view.replay([(negotiated, 'received'), (procedure, 'received')])
            window.replay_configuration_loaded({'selected_config': negotiated,
                                                'procedure': procedure})

            self.assertEqual(window.mode, OperationMode.HOSTLESS_CS)
            self.assertIsNone(window.controller_view.requested)
            rows = compare_procedure(window.controller_view.requested,
                                     window.controller_view.reports.current()[1], None)
            self.assertEqual({row.requested for row in rows}, {'—'})
            self.assertEqual({row.status for row in rows}, {INFO})
        finally:
            window.close()

    def test_procedure_disable_report_keeps_the_planner_schedule(self):
        """The disable report after a run leaves the planner on the last enabled procedure."""
        window = MainWindow(simulate=True)
        try:
            enabled = replace(window.cs_view.scenario.procedure, state=1, subevent_len=20000)
            window.cs_packet_received(enabled)
            window.cs_packet_received(replace(enabled, state=0))

            self.assertEqual(window.cs_view.scenario.procedure, enabled)
            self.assertEqual(window.controller_view.reports.current()[1].state, 0)
        finally:
            window.close()

    def test_replay_context_skips_procedure_disable_reports(self):
        from ble_channel_sounding.planner.model import Scenario
        from ble_channel_sounding.views.results_view import ResultsWidget
        enabled = replace(Scenario().procedure, state=1)
        context = ResultsWidget._replay_packet_context([(0, enabled), (1, replace(enabled, state=0))])
        self.assertIs(context["procedure"], enabled)
        self.assertNotIn("procedure", ResultsWidget._replay_packet_context([(0, replace(enabled, state=0))]))

    def test_hostless_recording_carries_no_host_configuration(self):
        """The editor keeps a configuration for the other modes; a hostless run is not it."""
        window = MainWindow(simulate=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.recording_view.folder.setText(directory)
                self.assertIsNotNone(window.session.host_config)
                window.select_role(OperationMode.HOSTLESS_CS)
                recorder = window.create_recording(window.session, True)
                try:
                    self.assertIsNone(recorder.config)
                    self.assertFalse(recorder.write_config)
                    self.assertEqual(recorder.scenario_json, '')
                    self.assertTrue(Path(recorder.path).name.startswith('hostless_cs_'))
                finally:
                    recorder.close()
                self.assertFalse(window.recording_view.config_path_for(Path(recorder.path)).exists())
        finally:
            window._active_recording_path = None
            window.close()

    def test_preferred_t_pm_reaches_the_client_and_comes_back(self):
        from ble_channel_sounding.protocol.packets import TpmPacket
        window = MainWindow(simulate=True)
        try:
            with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
                window.connect_port('Simulator', 921600)
                self.app.processEvents()
            t_pm = window.cs_view.host_controls['t_pm']
            t_pm.setCurrentIndex(t_pm.findData(40))
            window.cs_view.flush_edits()
            window.apply()
            self.app.processEvents()
            window.scan_peers()
            window.connect_selected_peer()
            self.assertEqual(window.simulator.config.t_pm, 40)
            self.assertTrue(any(isinstance(p, TpmPacket) for p in window.collect_config().packets()))
            self.assertTrue(window.session.in_sync)
            # The client's configuration restores the setting, and the run is compared against it.
            window.cs_view.host_settings['t_pm'] = 10
            window.config_received(window.session.client_config)
            self.assertEqual(window.cs_view.host_settings['t_pm'], 40)
            self.assertEqual(window.controller_view.requested_t_pm, 40)
            window.start()
            self.app.processEvents()
            rows = {window.controller_view.configuration.item(row, 0).text():
                    window.controller_view.configuration.item(row, 1).text()
                    for row in range(window.controller_view.configuration.rowCount())}
            self.assertEqual(rows['T_PM'], '40 µs')
            window.session.stop()
        finally:
            window.close()

    def test_controller_rows_follow_cs_mode(self):
        from ble_channel_sounding.views.controller_view import ControllerView
        from ble_channel_sounding.planner.model import Scenario
        view = ControllerView()
        try:
            view.add_packet(Scenario().configuration)
            rows = lambda: {view.configuration.item(row, 0).text() for row in range(view.configuration.rowCount())}
            view.set_mode(2)
            self.assertNotIn("RTT type", rows())
            self.assertIn("T_PM", rows())
            view.set_mode(1)
            self.assertIn("RTT type", rows())
            self.assertFalse({"T_IP2", "T_PM", "IPT (enhancements 1)"} & rows())
            view.set_mode(0x12)
            self.assertTrue({"RTT type", "T_PM", "Min main-mode steps"} <= rows())
        finally:
            view.close()

    @unittest.skip(FUTURE_RADIO_TEST)
    def test_radio_mode_makes_cs_views_dormant(self):
        window = MainWindow(simulate=True)
        try:
            results = window.tabs.indexOf(window.results_stack)
            self.assertEqual(window.tabs.tabText(results), "Results")
            self.assertIs(window.results_stack.currentWidget(), window.results)
            self.assertEqual(window.results.tabs.indexOf(window.controller_view), 0)
            self.assertEqual(window.results.tabs.tabText(0), "Controller")
            self.assertFalse(hasattr(window.controller_view, "summary"))
            self.assertEqual(window.results.status_summary.text(), window.controller_view.status_text)
            # History left Results for the Session tab (§7.8).
            self.assertEqual([window.results.tabs.tabText(i) for i in range(window.results.tabs.count())],
                             ["Controller", "FAE", "PBR per channel", "RTT", "Estimates"])
            window.results.tabs.setCurrentIndex(window.results.tabs.indexOf(window.results.fae_panel))
            self.assertTrue(window.results.procedure_controls.isHidden())
            self.assertTrue(window.results.pbr_controls.isHidden())
            self.assertTrue(window.results.rtt_controls.isHidden())
            window.results.tabs.setCurrentIndex(window.results.tabs.indexOf(window.results.pbr_page))
            self.assertNotEqual(window.results.status_summary.text(), window.controller_view.status_text)
            window.results.tabs.setCurrentIndex(0)
            self.assertEqual(window.results.status_summary.text(), window.controller_view.status_text)
            window.tabs.setCurrentIndex(results)
            window.select_role(OperationMode.RADIO_TX_TEST)
            self.assertEqual(window.tabs.tabText(results), "Radio RX results")
            self.assertIs(window.results_stack.currentWidget(), window.radio_results)
            self.assertTrue(window.tabs.isTabEnabled(results))
            self.assertTrue(window.cs_view.dormant)
            self.assertFalse(window.cs_view.isEnabled())
            with patch.object(window.results.fae_panel, 'add_packet') as fae, \
                    patch.object(window.results, 'add_packet') as result:
                window.packet_received(CsFaeTablePacket(1, 32))
            fae.assert_not_called()
            result.assert_not_called()
            with patch.object(PlannerWidget, 'refresh') as refresh:
                window.cs_view.controls['procedure.subevent_len'].setValue(
                    window.cs_view.controls['procedure.subevent_len'].value() + 1)
                window.cs_view.flush_edits()
                window.cs_view.timer.timeout.emit()
                refresh.assert_not_called()
                window.select_role(OperationMode.CS_INITIATOR)
                refresh.assert_called_once()
            self.assertFalse(window.cs_view.dormant)
            self.assertEqual(window.tabs.tabText(results), "Results")
            self.assertIs(window.results_stack.currentWidget(), window.results)
            self.assertTrue(window.tabs.isTabEnabled(results))
        finally:
            window.close()
