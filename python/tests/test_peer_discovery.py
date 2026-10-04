import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch
from PyQt6 import QtCore, QtWidgets as W
from ble_channel_sounding.protocol.packets import *
from ble_channel_sounding.protocol.frame import Frame, ProtocolError
from ble_channel_sounding.session import ClientSession, interruption_text
from ble_channel_sounding.simulator import Simulator
from ble_channel_sounding.app import MainWindow
from ble_channel_sounding.views.sync_dialog import SyncDialog


def peer(address=b'\x01\x02\x03\x04\x05\x06', name='Peer å', flags=3):
    raw = name.encode()
    return ScanResultPacket(1, address, -56, flags, len(raw), raw.ljust(254, b'\0'))


class PeerDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_wire_round_trips(self):
        for packet, size in ((ScanStartPacket(), 12), (AdvertiseStartPacket(), 12),
                             (PeerConnectPacket(1, b'123456'), 19), (peer(), 276)):
            self.assertEqual(len(packet.to_bytes()), size)
            self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
        self.assertEqual(peer().address_text, '06:05:04:03:02:01')
        self.assertEqual(peer().peer_name, 'Peer å')
        self.assertEqual(PeerConnectPacket(1, b'123456').to_frame().payload, b'\x01123456')
        self.assertEqual(peer(name='x'*254).name_length, 254)

    def test_reject_invalid_wire(self):
        for construct in (lambda: PeerConnectPacket(2, b'123456'),
                          lambda: PeerConnectPacket(1, b'12'),
                          lambda: replace(peer(), name_length=255),
                          lambda: replace(peer(), name_length=0),
                          lambda: replace(peer(), flags=4)):
            with self.assertRaises(ProtocolError):
                construct()

    def test_merge_scan_response_and_duplicate_names(self):
        session = ClientSession()
        session.receive(peer(name='', flags=1))
        session.receive(peer(flags=2))
        session.receive(peer(name='', flags=0))
        session.receive(peer(address=b'654321'))
        self.assertEqual(len(session.peers), 2)
        first = session.peers[(1, b'\x01\x02\x03\x04\x05\x06')]
        self.assertEqual(first.peer_name, 'Peer å')
        self.assertEqual(first.flags, 3)

    def test_visible_peers_follow_applied_prefixes(self):
        session = ClientSession()
        session.receive(peer(address=b'111111', name='CS-Tag'))
        session.receive(peer(address=b'222222', name='Lab'))
        session.receive(peer(address=b'333333', name='', flags=1))
        session.receive(peer(address=b'444444', name='cs-lower'))
        self.assertEqual(len(session.visible_peers()), 4)  # no configuration: every peer
        config = MagicMock(patterns=PeripheralPatternsPacket.from_patterns(['CS', 'La']))
        session.host_config = config
        self.assertEqual(sorted(k[1] for k in session.visible_peers()), [b'111111', b'222222'])
        self.assertEqual(len(session.visible_peers(show_all=True)), 4)
        config.patterns = None
        self.assertEqual(len(session.visible_peers()), 4)
        # A scan response naming the unnamed peer brings it into the list.
        config.patterns = PeripheralPatternsPacket.from_patterns(['CS'])
        session.receive(peer(address=b'333333', name='CS-Late', flags=2))
        self.assertIn((1, b'333333'), session.visible_peers())

    def window(self):
        window = MainWindow(simulate=True)
        # Cleanups run last-in, first-out: stop the timers, close, then delete the window now
        # rather than at some later event loop, where a leftover main window stops later GUI
        # tests from receiving hover events.
        self.addCleanup(QtCore.QCoreApplication.sendPostedEvents, None, QtCore.QEvent.Type.DeferredDelete)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        self.addCleanup(window.qt.timer.stop)
        self.addCleanup(window.poll.stop)
        with patch.object(SyncDialog, 'exec', lambda dialog: dialog.choose('apply')):
            window.connect_port('Simulator', 921600)
            self.app.processEvents()
        return window

    def test_gui_selects_second_peer_with_duplicate_name(self):
        window = self.window()
        window.scan_peers()
        # 'Lab peer å' is outside the default 'CS' prefix until Show all.
        self.assertEqual(window.peers_view.peers.count(), 2)
        window.peers_view.show_all.setChecked(True)
        self.assertEqual(window.peers_view.peers.count(), 3)
        window.peers_view.show_all.setChecked(False)
        self.assertEqual(window.peers_view.peers.count(), 2)
        window.peers_view.peers.setCurrentIndex(1)
        window.update_controls()
        self.assertTrue(window.peers_view.connect.isEnabled())
        key = window.peers_view.peers.currentData()
        window.connect_selected_peer()
        self.assertEqual(window.simulator.selected_peer, key)
        self.assertEqual(window.session.link_state, ClientState.LINK_CONNECTED)
        # Disconnect link ends the host session with the link (§7.8); scanning
        # again means a new session over the port it left open.
        window.session.disconnect_link()
        self.assertEqual(window.session.state, 'DISCONNECTED')
        self.assertIsNotNone(window.session.transport)
        window.session.reconnect()
        window.scan_peers()
        self.assertEqual(len(window.session.peers), 3)
        window.session.stop()
        self.assertEqual(window.session.link_state, ClientState.LINK_DISCONNECTED)

    def test_guards_and_security_failure(self):
        window = self.window()
        with self.assertRaises(ValueError):
            window.session.connect_peer((1, b'123456'))
        window.scan_peers()
        with self.assertRaises(ValueError):
            window.session.advertise()
        report = ClientStatePacket(ClientState.ERROR, 0, RejectReason.SECURITY_FAILED, 5, -13)
        self.assertIn('SECURITY_FAILED', interruption_text(report))
        self.assertIn('0x05', interruption_text(report))

    def test_scan_continues_and_toolbar_can_restart_before_connecting(self):
        window = self.window()
        scan = window.run_bar.buttons['Scan']
        with patch.object(window, 'show_alert') as alert:
            scan.click()
            self.app.processEvents()
            self.assertEqual(window.session.link_state, ClientState.SCANNING)
            self.assertEqual(window.peers_view.peers.count(), 2)
            self.assertFalse(hasattr(window.simulator, 'selected_peer'))
            self.assertTrue(scan.isEnabled())
            alert.assert_not_called()

            # Another matching device can arrive after the initial matches.
            window.simulator.send(peer(address=b'654321', name='CS-Late'))
            self.assertEqual(window.peers_view.peers.count(), 3)
            self.assertEqual(window.session.link_state, ClientState.SCANNING)
            original = window.simulator.handle
            with patch.object(window.simulator, 'handle',
                              side_effect=lambda packet: None if isinstance(packet, StopPacket) else original(packet)):
                scan.click()
                self.app.processEvents()
                self.assertFalse(scan.isEnabled())
                window.simulator.send(peer(address=b'654321', name='CS-Late'))
                self.assertEqual(window.peers_view.peers.count(), 1)
                original(StopPacket())
                self.app.processEvents()
            self.assertEqual(window.peers_view.peers.count(), 2)
            self.assertNotIn((1, b'654321'), window.session.peers)
            self.assertEqual(window.session.link_state, ClientState.SCANNING)
            self.assertTrue(scan.isEnabled())
            self.assertIsNone(window.session.pending)
            self.assertFalse(window.session.queue)
            alert.assert_not_called()

        window.connect_selected_peer()
        self.assertEqual(window.session.link_state, ClientState.LINK_CONNECTED)
        self.assertFalse(scan.isEnabled())

    def test_peripheral_advertising(self):
        window = self.window()
        cfg = window.session.host_config
        cfg = replace(cfg, config=replace(cfg.config, gap_role=1))
        window.session.set_host_config(cfg)
        window.session.apply()
        window.session.advertise()
        self.assertEqual(window.session.link_state, ClientState.ADVERTISING)
        window.session.stop()
        self.assertEqual(window.session.link_state, ClientState.LINK_DISCONNECTED)
