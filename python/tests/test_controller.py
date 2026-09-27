"""Controller report decoding, comparison and compatibility checks; no Qt dependency."""
from dataclasses import fields, replace
import importlib.util
import os
import unittest

from ble_channel_sounding.controller import (DIFFERS, OK, OUTSIDE, RUN_FAILS, ControllerReports, capability_rows, check_compatibility,
                               compare_configuration, compare_connection, compare_procedure, source_label)
from ble_channel_sounding.planner.bridge import apply_packet, config_packet
from ble_channel_sounding.planner.model import Scenario
from ble_channel_sounding.protocol.packets import (CAPABILITIES_CONN_NONE, CapabilitiesSource, ConnectionParametersPacket,
                                     CsCapabilitiesPacket, OperationMode, packet_from_dict, packet_to_dict)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = all(importlib.util.find_spec(m) for m in ("PyQt6", "pyqtgraph"))


def capabilities(**overrides):
    values = {f.name: 0 for f in fields(CsCapabilitiesPacket)}
    values.update(conn_index=CAPABILITIES_CONN_NONE, num_config_supported=4, num_antennas_supported=4,
                  max_antenna_paths_supported=4, initiator_supported=1, reflector_supported=1, mode_3_supported=1,
                  rtt_aa_only_precision=1, rtt_aa_only_n=10, rtt_sounding_n=10, t_ip1_times_supported=0x7F, t_ip2_times_supported=0x7F,
                  t_fcs_times_supported=0x1FF, t_pm_times_supported=0x03, t_sw_time=2, tx_snr_capability=0x1F,
                  cs_sync_2m_phy_supported=1)
    values.update(overrides)
    return CsCapabilitiesPacket(**values)


def negotiated():
    """Host initiator request and the reports a controller would complete it with."""
    scenario = Scenario()
    requested = config_packet(scenario, {}, OperationMode.CS_INITIATOR)
    return requested, scenario.configuration, replace(scenario.procedure, state=1)


class ControllerTests(unittest.TestCase):
    def test_capabilities_frame_round_trip(self):
        packet = capabilities(source=CapabilitiesSource.REMOTE, conn_index=3, cs_ipt_reflector_supported=1)
        self.assertEqual(len(packet.to_bytes()), 49)
        self.assertEqual(CsCapabilitiesPacket.from_frame(packet.to_frame()), packet)
        data = {k: v for k, v in packet_to_dict(packet).items() if k not in ("packet_name", "packet_type")}
        self.assertEqual(packet_from_dict("cs_capabilities", data), packet)
        self.assertEqual(source_label(packet), "Remote (connection 3)")
        self.assertEqual(source_label(capabilities()), "Local")

    def test_capability_rows_decode_bitmasks(self):
        rows = {row.label: row for row in capability_rows(capabilities(t_pm_times_supported=0x02,
                                                                       tx_snr_capability=0x05))}
        self.assertEqual(rows["T_PM"].text, "20, 40 µs")
        self.assertEqual(rows["T_FCS"].text, "15, 20, 30, 40, 50, 60, 80, 100, 120, 150 µs")
        self.assertEqual(rows["TX SNR levels"].text, "18 dB, 24 dB")
        self.assertEqual(rows["RTT AA only"].text, "10 ns, N = 10")
        self.assertFalse(rows["RTT random payload"].supported)
        self.assertTrue(rows["Mode 3"].supported)

    def test_compare_matching_and_differing_values(self):
        requested, configuration, procedure = negotiated()
        rows = {row.field: row for row in compare_configuration(requested, configuration)}
        self.assertEqual(rows["Mode"].status, OK)
        self.assertEqual(rows["Channels"].status, OK)
        rows = {row.field: row for row in compare_configuration(requested, replace(configuration, mode_0_steps=1))}
        self.assertEqual(rows["Mode-0 steps"].status, DIFFERS)
        rows = {row.field: row for row in compare_procedure(requested, procedure)}
        self.assertEqual(rows["Subevent length"].status, OK)
        self.assertEqual(rows["Procedure interval"].status, OK)
        rows = {row.field: row for row in compare_procedure(
            requested, replace(procedure, subevent_len=requested.max_subevent_len + 1))}
        self.assertEqual(rows["Subevent length"].status, OUTSIDE)
        self.assertTrue(all(row.requested == "—" for row in compare_procedure(None, procedure)
                            if row.field == "Subevent length"))

    def test_connection_rows_compare_the_request(self):
        requested, _, _ = negotiated()
        reported = ConnectionParametersPacket(requested.connection_interval_min, requested.connection_latency,
                                              requested.connection_timeout, 498)
        rows = {row.field: row for row in compare_connection(requested, reported)}
        self.assertEqual((rows["Connection interval"].negotiated, rows["Connection interval"].status),
                         (f"{reported.interval * 1.25:g} ms", OK))
        self.assertEqual(rows["Peripheral latency"].status, OK)
        self.assertEqual(rows["Supervision timeout"].negotiated, f"{reported.timeout * 10} ms")
        self.assertEqual((rows["ATT MTU"].negotiated, rows["ATT MTU"].status), ("498 bytes", ""))
        # An interval the controller picked outside the requested range, and a changed latency.
        rows = {row.field: row for row in compare_connection(
            requested, replace(reported, interval=requested.connection_interval_max + 8, latency=2))}
        self.assertEqual(rows["Connection interval"].status, OUTSIDE)
        self.assertEqual((rows["Peripheral latency"].negotiated, rows["Peripheral latency"].status),
                         ("2 events", DIFFERS))
        # Only a GAP central asks for connection parameters (plan §3.1).
        rows = {row.field: row for row in compare_connection(replace(requested, gap_role=1), reported)}
        self.assertEqual({row.requested for row in rows.values()}, {"not requested"})
        self.assertEqual({row.status for row in rows.values()}, {""})
        rows = {row.field: row for row in compare_connection(None, reported)}
        self.assertEqual({row.requested for row in rows.values() if row.field != "ATT MTU"}, {"—"})
        self.assertEqual(rows["ATT MTU"].requested, "not requested")

    def test_procedure_intervals_use_the_reported_acl_interval(self):
        requested, _, procedure = negotiated()
        rows = {row.field: row for row in compare_procedure(requested, procedure)}
        self.assertEqual(rows["Event interval"].negotiated,
                         f"{procedure.event_interval} ACL events")
        self.assertEqual(rows["Procedure interval"].negotiated,
                         f"{procedure.procedure_interval} ACL events")
        # A requested range leaves the event counts without a millisecond equivalent.
        ranged = replace(requested, connection_interval_min=12, connection_interval_max=24)
        rows = {row.field: row for row in compare_procedure(ranged, procedure)}
        self.assertEqual(rows["Event interval"].negotiated, f"{procedure.event_interval} ACL events")
        rows = {row.field: row for row in compare_procedure(ranged, procedure,
                                                            ConnectionParametersPacket(12, 0, 400, 23))}
        self.assertEqual(rows["Event interval"].negotiated,
                         f"{procedure.event_interval} ACL events ({procedure.event_interval * 15:g} ms)")
        self.assertIn(f"({procedure.procedure_interval * 15:g} ms)", rows["Procedure interval"].negotiated)

    def test_requested_t_pm_is_compared_and_checked(self):
        requested, configuration, _ = negotiated()
        # Without a request T_PM is the controller's own choice.
        rows = {row.field: row for row in compare_configuration(requested, configuration)}
        self.assertEqual(rows["T_PM"].requested, "controller")
        rows = {row.field: row for row in compare_configuration(requested, replace(configuration, t_pm_time_us=40),
                                                                0, 40)}
        self.assertEqual((rows["T_PM"].requested, rows["T_PM"].negotiated, rows["T_PM"].status),
                         ("40 µs", "40 µs", OK))
        rows = {row.field: row for row in compare_configuration(requested, replace(configuration, t_pm_time_us=10),
                                                                0, 40)}
        self.assertEqual(rows["T_PM"].status, DIFFERS)
        # A request is checked against both sides before configuration complete.
        caps = {CapabilitiesSource.LOCAL: capabilities(),
                CapabilitiesSource.REMOTE: capabilities(source=1, t_pm_times_supported=0x01)}
        self.assertIn("Reflector (remote): T_PM 20 µs not supported",
                      check_compatibility(caps, requested=requested, t_pm=20))
        self.assertEqual(check_compatibility(caps, requested=requested, t_pm=40), [])
        self.assertEqual(check_compatibility(caps, requested=requested), [])

    def test_preferred_peer_antenna_beyond_the_reflector_fails_the_run(self):
        requested, _, _ = negotiated()
        caps = {CapabilitiesSource.LOCAL: capabilities(),
                CapabilitiesSource.REMOTE: capabilities(source=1, num_antennas_supported=2)}
        # Antenna 3 on a two-antenna reflector: cs_roles ends the setup at remote capabilities.
        issues = check_compatibility(caps, requested=replace(requested, preferred_peer_antenna=4))
        self.assertIn(f"{RUN_FAILS}Reflector (remote): preferred peer antenna 0x04 names an antenna beyond its 2",
                      issues)
        self.assertEqual(check_compatibility(caps, requested=replace(requested, preferred_peer_antenna=3)), [])
        # A reflector request names initiator antennas; cs_roles checks only the initiator's.
        reflector = config_packet(Scenario(), {"preferred_peer_antenna": 4}, OperationMode.CS_REFLECTOR)
        self.assertEqual(check_compatibility(caps, requested=reflector), [])

    def test_compatibility_reports_unsupported_settings_per_side(self):
        requested, configuration, procedure = negotiated()
        caps = {CapabilitiesSource.LOCAL: capabilities(), CapabilitiesSource.REMOTE: capabilities()}
        self.assertEqual(check_compatibility(caps, requested=requested, configuration=configuration,
                                             procedure=procedure), [])
        configuration = replace(configuration, mode=3, cs_sync_phy=2, t_pm_time_us=20)
        caps[CapabilitiesSource.LOCAL] = capabilities(cs_sync_2m_phy_supported=0)
        caps[CapabilitiesSource.REMOTE] = capabilities(source=1, mode_3_supported=0, t_pm_times_supported=0x01,
                                                       max_antenna_paths_supported=1, cs_sync_2m_phy_supported=0)
        issues = check_compatibility(caps, requested=requested, configuration=configuration,
                                     procedure=replace(procedure, tone_antenna_config_selection=7))
        self.assertIn("Reflector (remote): mode 3 not supported", issues)
        self.assertIn("Initiator (local): CS_SYNC LE 2M not supported", issues)
        self.assertIn("Reflector (remote): CS_SYNC LE 2M not supported", issues)
        self.assertIn("Reflector (remote): T_PM 20 µs not supported", issues)
        self.assertIn("Reflector (remote): 4 antenna paths needed, 1 supported", issues)
        self.assertNotIn("Initiator (local): mode 3 not supported", issues)

    def test_missing_ipt_fails_the_run_with_reflector_data_none(self):
        requested, configuration, procedure = negotiated()
        caps = {CapabilitiesSource.LOCAL: capabilities(),
                CapabilitiesSource.REMOTE: capabilities(source=1, cs_ipt_reflector_supported=0)}
        ipt = replace(configuration, cs_enhancements_1=1)
        # With RAS a missing IPT only degrades the run.
        self.assertIn("Reflector (remote): IPT not supported",
                      check_compatibility(caps, requested=requested, configuration=ipt, procedure=procedure))
        issues = check_compatibility(caps, requested=requested, configuration=ipt, procedure=procedure,
                                     peer_data=1)
        self.assertEqual(issues[0], RUN_FAILS + "Reflector (remote): IPT not supported, needed for reflector data none")
        # The controller created the configuration without IPT.
        issues = check_compatibility(caps, requested=requested, configuration=configuration, procedure=procedure,
                                     peer_data=1)
        self.assertEqual(issues[0], RUN_FAILS + "configuration: IPT not enabled, needed for reflector data none")

    def test_compatibility_before_link_uses_request_and_local_only(self):
        requested, _, _ = negotiated()
        requested = replace(requested, creation_channel_selection_type=1, snr_control_initiator=4)
        caps = {CapabilitiesSource.LOCAL: capabilities(chsel_alg_3c_supported=0, tx_snr_capability=0x01)}
        self.assertEqual(check_compatibility(caps, requested=requested),
                         ["Initiator (local): CSA #3c not supported",
                          "Initiator (local): SNR control 30 dB not supported"])
        self.assertEqual(check_compatibility({}, requested=requested), [])

    def test_reports_keep_latest_per_source_and_id(self):
        _, configuration, procedure = negotiated()
        reports = ControllerReports()
        connection = ConnectionParametersPacket(24, 0, 400, 23)
        for packet in (capabilities(), capabilities(num_config_supported=2), capabilities(source=1), configuration,
                       procedure, connection, replace(connection, latency=1)):
            self.assertTrue(reports.add(packet))
        self.assertFalse(reports.add(object()))
        self.assertEqual(reports.capabilities[CapabilitiesSource.LOCAL].num_config_supported, 2)
        self.assertEqual(reports.current(), (configuration, procedure))
        self.assertEqual(reports.connection.latency, 1)
        reports.clear()
        self.assertEqual(reports.current(), (None, None))
        self.assertIsNone(reports.connection)

    def test_disable_report_keeps_the_enabled_procedure(self):
        """A disable report's parameters are ignored (Core Vol 4, Part E, §7.7.65.43); only the state changes."""
        _, configuration, procedure = negotiated()
        reports = ControllerReports()
        disabled = replace(procedure, state=0, tone_antenna_config_selection=27, subevent_len=0)
        self.assertTrue(reports.add(disabled))
        self.assertEqual(reports.current(), (None, None))
        reports.add(configuration)
        reports.add(procedure)
        reports.add(disabled)
        self.assertEqual(reports.current(), (configuration, replace(procedure, state=0)))


@unittest.skipUnless(GUI_AVAILABLE, "PyQt6 and pyqtgraph are required")
class ControllerViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_view_fills_tables_and_issues(self):
        from ble_channel_sounding.views.controller_view import ControllerView
        requested, configuration, procedure = negotiated()
        view = ControllerView()
        self.assertEqual(view.capabilities.rowCount(), 0)
        view.set_requested(requested)
        for packet in (capabilities(), capabilities(source=1, mode_3_supported=0),
                       replace(configuration, mode=3), procedure):
            view.add_packet(packet)
        self.assertEqual(view.capabilities.columnCount(), 3)
        self.assertGreater(view.capabilities.rowCount(), 20)
        self.assertEqual(view.capabilities.horizontalHeaderItem(2).text(), "Remote")
        self.assertEqual(view.configuration.item(2, 3).text(), "differs")
        self.assertIn("Reflector (remote): mode 3 not supported", view.issue_list())
        # The summary goes to the shared Results status line.
        self.assertIn("1 compatibility issue", view.status_text)
        view.clear()
        self.assertEqual(view.configuration.rowCount(), 0)
        self.assertEqual(view.issues.item(0).text(), "Waiting for capabilities reports")

    def test_view_shows_connection_parameters_when_reported(self):
        from ble_channel_sounding.views.controller_view import ControllerView
        requested, _, procedure = negotiated()
        view = ControllerView()
        view.set_requested(requested)
        self.assertEqual(view.connection.rowCount(), 0)
        self.assertIn("not received", view.connection_box.title())
        view.add_packet(procedure)
        events = view.procedure.item(7, 2).text()
        view.add_packet(ConnectionParametersPacket(requested.connection_interval_min, 1,
                                                   requested.connection_timeout, 23))
        self.assertEqual(view.connection.rowCount(), 4)
        self.assertEqual(view.connection.item(0, 0).text(), "Connection interval")
        self.assertEqual(view.connection.item(1, 3).text(), "differs")
        self.assertEqual(view.connection.item(3, 0).text(), "ATT MTU")
        self.assertEqual(view.connection_box.title(), "Connection parameters")
        # The reported interval also gives the procedure event counts a duration.
        self.assertEqual(view.procedure.item(7, 0).text(), "Event interval")
        self.assertIn(events, view.procedure.item(7, 2).text())
        self.assertIn(" ms)", view.procedure.item(7, 2).text())
        view.clear()
        self.assertEqual(view.connection.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
