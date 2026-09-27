"""Checks for cs_app.report_log wording and the Session view that uses it."""

import importlib.util
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from cs_app.protocol.frame import Frame
from cs_app.protocol.packets import (ClientState, ClientStatePacket, CommandResponsePacket, CsInitiatorSubeventResultPacket,
                                     CsReflectorSubeventResultPacket, LogMessagePacket, OperationMode, PacketType,
                                     ConnectionParametersPacket, ProtocolStatus, RasDataLostPacket, RejectReason,
                                     StartPacket)
from cs_app.report_log import (CLIENT_LOG, COMMANDS, ERROR, INFO, SUBEVENTS, WARNING, describe_received,
                               describe_sent)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = all(importlib.util.find_spec(m) for m in ("PyQt6", "pyqtgraph"))


def subevent(cls, **changes):
    values = dict(config_id=0, start_acl_conn_event=15854, procedure_counter=5265, frequency_compensation=0,
                  reference_power_level=0, procedure_done_status=0, subevent_done_status=0,
                  procedure_abort_reason=0, subevent_abort_reason=0, num_antenna_paths=1, abort_step=0)
    values.update(changes)
    return cls(**values)


class ReportLogTests(unittest.TestCase):
    def test_subevent_lines_name_the_role(self):
        for cls, role in ((CsInitiatorSubeventResultPacket, "initiator"), (CsReflectorSubeventResultPacket, "reflector")):
            with self.subTest(role=role):
                line = describe_received(subevent(cls))
                self.assertEqual((line.level, line.category), (INFO, SUBEVENTS))
                self.assertTrue(line.text.startswith(f"CS {role} subevent: config 0, event 15854, procedure 5265, steps 0"))

    def test_aborted_subevent_is_a_warning(self):
        line = describe_received(subevent(CsReflectorSubeventResultPacket, subevent_abort_reason=0x0F, abort_step=12))
        self.assertEqual(line.level, WARNING)
        self.assertIn("abort reasons 0x00/0x0f at step 12", line.text)

    def test_client_state_includes_failure_details(self):
        line = describe_received(ClientStatePacket(ClientState.LINK_LOST, OperationMode.CS_INITIATOR,
                                                   RejectReason.INTERRUPTED, 0x08, -140))
        self.assertEqual(line.level, WARNING)
        self.assertEqual(line.text, "State LINK_LOST, mode CS_INITIATOR, reason INTERRUPTED, "
                                    "HCI status 0x08, error -ECANCELED")

    def test_command_response_and_sent_command(self):
        line = describe_received(CommandResponsePacket(PacketType.START, ProtocolStatus.CONFIG_MISMATCH, 0, 0, 0))
        self.assertEqual((line.level, line.category), (ERROR, COMMANDS))
        self.assertEqual(line.text, "START response CONFIG_MISMATCH")
        self.assertEqual(describe_sent(StartPacket(0x1234ABCD)).text, "START (configuration CRC 0x1234abcd)")

    def test_client_log_and_other_reports(self):
        line = describe_received(LogMessagePacket(b"Peer link encrypted\n"))
        self.assertEqual((line.category, line.text), (CLIENT_LOG, "Peer link encrypted"))
        # app_log.c prefixes the level; the line keeps its text and takes the level.
        self.assertEqual(describe_received(LogMessagePacket(b"<wrn> cs_roles: RAS late\n")).level, WARNING)
        self.assertEqual(describe_received(LogMessagePacket(b"<err> host_link: overrun")).level, ERROR)
        self.assertEqual(describe_received(LogMessagePacket(b"<dbg> cs_roles: step")).level, INFO)
        self.assertEqual(describe_received(RasDataLostPacket(7, -61)).text, "RAS data lost: procedure 7, error -ENODATA")
        from cs_app.planner.model import Scenario
        disabled = replace(Scenario().procedure, config_id=2, state=0, tone_antenna_config_selection=27)
        self.assertEqual(describe_received(disabled).text, "Procedures off: config 2")
        from cs_app.protocol.packets import CsPeerDataPacket
        self.assertEqual(describe_received(CsPeerDataPacket(1)).text, "Reflector data: none (initiator only)")
        self.assertEqual(
            describe_received(ConnectionParametersPacket(14, 0, 400, 498)).text,
            "ACL connection parameters: interval 17.5 ms, latency 0 events, timeout 4000 ms, ATT MTU 498 bytes",
        )
        self.assertEqual(describe_received(Frame(0x7777, b"abc")).text, "Unknown frame type 0x7777, 3 bytes")


@unittest.skipUnless(GUI_AVAILABLE, "PyQt6 and pyqtgraph are required")
class SessionViewTests(unittest.TestCase):
    """The Session tab replaced the Session log (implementation_plan.md §7.8)."""

    @classmethod
    def setUpClass(cls):
        from PyQt6 import QtWidgets as W
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_filters_hide_info_but_not_warnings(self):
        from cs_app.views.results_view import ResultsWidget
        window = ResultsWidget()
        view = window.session_view
        window.add_packet(subevent(CsInitiatorSubeventResultPacket))
        window.add_packet(subevent(CsReflectorSubeventResultPacket, procedure_abort_reason=1))
        window.add_packet(LogMessagePacket(b"<err> cs_roles: setup failed"))
        window.refresh()
        view.types["subevent"].setChecked(False)
        view.types["log"].setChecked(False)
        model = view.model
        rows = [[model.data(model.index(row, column)) for column in range(5)] for row in range(model.rowCount())]
        self.assertEqual([row[4] for row in rows][0][:26], "CS reflector subevent: con")
        self.assertEqual([row[2] for row in rows], ["Subevent · wrn", "Client log · err"])
        self.assertEqual(view.counts_label.text(), "1 warnings · 1 errors")
        window.close()

    def test_simulated_session_shows_commands_and_responses(self):
        from cs_app.app import MainWindow
        window = MainWindow(simulate=True)
        try:
            from cs_app.simulator import Simulator
            with patch.object(window, "resolve_sync"):
                window.session.connect(Simulator().transport)
                self.app.processEvents()
            window.results.refresh()
            model = window.session_view.model
            rows = [(model.data(model.index(row, 1)), model.data(model.index(row, 4)))
                    for row in range(model.rowCount())]
            self.assertIn(("Sent", "CONNECT"), rows)
            self.assertTrue(any(direction == "Received" and text.startswith("Connect response OK")
                                for direction, text in rows))
        finally:
            window.close()

if __name__ == "__main__":
    unittest.main()
