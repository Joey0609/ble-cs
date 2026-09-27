"""Optional offscreen GUI checks: QT_QPA_PLATFORM=offscreen python -m unittest ..."""

from dataclasses import replace
import importlib.util
import os
import tempfile
import unittest
import unittest.mock
from html import escape
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = all(importlib.util.find_spec(m) for m in ("PyQt6", "pyqtgraph"))


@unittest.skipUnless(GUI_AVAILABLE, "Install the gui extra for Qt checks")
class PlannerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ble_channel_sounding.views.cs_view import PlannerWidget
        self.window = PlannerWidget()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_five_views_render_and_navigation_drills_down(self):
        w = self.window
        w.apply_config(replace(w.scenario, target_steps=20))
        self.assertEqual(w.views.count(), 5)
        self.assertTrue(w.schedule.complete)
        se = w.schedule.subevents[-1]
        w.select_step(se.index, se.steps[-1].index)
        self.assertEqual(w.views.currentIndex(), 3)
        self.assertEqual(w.event_select.currentData(), se.event)
        self.assertEqual(w.subevent_select.currentData(), se.index)
        self.assertIn("Mode 2", w.step_info.text())
        with tempfile.TemporaryDirectory() as directory:
            for i in range(5):
                w.views.setCurrentIndex(i)
                self.app.processEvents()
                file = Path(directory) / f"view-{i}.png"
                self.assertTrue(w.views.currentWidget().grab().save(str(file)))
                self.assertGreater(file.stat().st_size, 1000)

    def test_live_edit_recomputes_and_invalid_values_clear_drilldown(self):
        from PyQt6.QtTest import QTest
        w = self.window
        w.controls["target_steps"].setValue(20)
        QTest.qWait(150)
        self.assertEqual(w.schedule.completed_steps, 20)
        w.controls["procedure.subevent_interval"].setValue(1)
        QTest.qWait(150)
        self.assertTrue(w.schedule.errors)
        self.assertEqual(w.step_select.count(), 0)
        self.assertIn("No step available", w.step_info.text())

    def test_controller_dataclasses_can_be_applied(self):
        from dataclasses import replace
        w = self.window
        config = replace(w.scenario.configuration, mode=3)
        w.apply_controller_packets(config, w.scenario.procedure)
        self.assertEqual(w.controls["configuration.mode"].currentData(), 3)
        self.assertIn("Controller fields supplied", w.source.text())
        self.assertEqual(w.scenario.configuration.to_bytes(), config.to_bytes())

    def test_apply_config_from_frames_updates_view_atomically(self):
        from dataclasses import replace
        from ble_channel_sounding.protocol.frame import Frame
        w = self.window
        config = replace(w.scenario.configuration, mode=3, t_fcs_time_us=100)
        procedure = replace(w.scenario.procedure, subevent_len=6000)
        with self.assertRaises(ValueError):
            w.apply_config(config.to_frame(), b"not a frame")
        self.assertEqual(w.scenario.configuration.mode, 2)
        w.apply_config(Frame(config.PACKET_TYPE, config.to_frame().payload), procedure.to_bytes())
        self.assertEqual(w.controls["configuration.mode"].currentData(), 3)
        self.assertEqual(w.controls["configuration.t_fcs_time_us"].currentData(), 100)
        self.assertEqual(w.controls["procedure.subevent_len"].value(), 6000)
        self.assertIn("Controller fields supplied", w.source.text())
        # Unedited controls reproduce the applied fields exactly.
        self.assertEqual(w.read_controls().configuration, config)
        w.reset()
        self.assertEqual(w.scenario, w.read_controls())

    def test_apply_channel_list_updates_editor_and_view(self):
        w = self.window
        w.apply_channel_list(range(26, 54))
        self.assertEqual(w.controls["configuration.channel_map"].summary.text(), "28 of 72 channels enabled")
        self.assertIn("28 of 72 channels enabled", w.channel_info.text())
        self.assertTrue(all(26 <= st.channel < 54 for se in w.schedule.subevents for st in se.steps))

    def test_typed_hex_channel_map_is_saved_without_focus_change(self):
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.planner.model import loads
        w = self.window
        editor = w.controls["configuration.channel_map"]
        editor.hex.setFocus()
        editor.hex.selectAll()
        QTest.keyClicks(editor.hex, "fcff7ffcffff00ffff1f")
        # Save as the toolbar does: no editingFinished, since macOS buttons take no focus.
        w.flush_edits()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            with unittest.mock.patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                w.save_file()
            self.assertEqual(loads(path.read_text()).configuration.channel_map.hex(), "fcff7ffcffff00ffff1f")

    @unittest.skip("Future: the integrated client supports only the CS initiator role")
    def test_collect_config_builds_a_reflector_packet(self):
        from ble_channel_sounding.protocol.packets import CsReflectorConfigPacket, OperationMode
        self.assertIsInstance(self.window.collect_config(OperationMode.CS_REFLECTOR), CsReflectorConfigPacket)

    def test_collect_config_builds_transmittable_packet(self):
        from dataclasses import replace
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.protocol.packets import CsInitiatorConfigPacket
        w = self.window
        w.controls["configuration.mode"].setCurrentIndex(w.controls["configuration.mode"].findData(3))
        w.apply_channel_list(range(26, 76))  # also folds the pending edit into the scenario
        packet = w.collect_config()
        self.assertIsInstance(packet, CsInitiatorConfigPacket)
        self.assertEqual(packet.creation_mode, 3)
        self.assertEqual(packet.creation_channel_map, w.scenario.configuration.channel_map)
        # A received host config round-trips, including fields the planner does not show.
        w.apply_config(replace(packet, max_tx_power=-8, gap_role=1))
        self.assertEqual(w.collect_config().max_tx_power, -8)
        w.controls["procedure.subevent_interval"].setValue(1)
        QTest.qWait(10)  # still pending: collect must fold it in and refuse
        with self.assertRaises(ValueError):
            w.collect_config()

    def test_operation_mode_and_ipt_are_saved_with_the_scenario(self):
        from ble_channel_sounding.planner.model import Scenario
        from ble_channel_sounding.protocol.packets import CsReflectorConfigPacket, OperationMode
        w = self.window
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_REFLECTOR))
        ipt = w.controls["configuration.cs_enhancements_1"]
        ipt.setCurrentIndex(ipt.findData(1))
        w.flush_edits()
        self.assertEqual(w.scenario.configuration.role, 1)
        self.assertEqual(w.scenario.configuration.cs_enhancements_1, 1)
        self.assertIsInstance(w.collect_config(), CsReflectorConfigPacket)
        self.assertEqual(w.collect_config(OperationMode.CS_INITIATOR).creation_cs_enhancements_1, 1)
        self.assertTrue(w.controls["t_sw_ipt_us"].isEnabled())
        self.assertFalse(w.controls["t_sw_us"].isEnabled())
        w.controls["t_sw_ipt_us"].setCurrentIndex(w.controls["t_sw_ipt_us"].findData(10))
        w.flush_edits()
        se = w.schedule.subevents[0]
        w.select_step(se.index, se.steps[-1].index)
        self.assertIn("T_SW_IPT = 10 µs", w.step_info.text())
        w.apply_config(Scenario())
        self.assertEqual(w.target_mode.currentData(), OperationMode.CS_INITIATOR)
        self.assertEqual(ipt.currentData(), 0)
        self.assertFalse(w.controls["t_sw_ipt_us"].isEnabled())

    def test_preferred_t_pm_is_an_initiator_pbr_setting_that_the_prediction_follows(self):
        from ble_channel_sounding.protocol.packets import OperationMode
        w = self.window
        t_pm, example = w.host_controls["t_pm"], w.controls["configuration.t_pm_time_us"]
        mode = w.controls["configuration.mode"]
        mode.setCurrentIndex(mode.findData(2))
        self.assertTrue(t_pm.isEnabled())
        self.assertEqual(w.host_settings["t_pm"], 40)
        # Asking for a T_PM also moves the example value the prediction uses.
        t_pm.setCurrentIndex(t_pm.findData(40))
        w.flush_edits()
        self.assertEqual((w.host_settings["t_pm"], w.scenario.configuration.t_pm_time_us), (40, 40))
        # The example stays editable, so a negotiated report can differ from the request.
        w.set_control_value(example, 20)
        w.flush_edits()
        self.assertEqual((w.host_settings["t_pm"], w.scenario.configuration.t_pm_time_us), (40, 20))
        # Only a CS initiator sends SET_T_PM, and only Mode 2 or 3 has tone slots.
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_REFLECTOR))
        self.assertFalse(t_pm.isEnabled())
        self.assertEqual(w.host_settings["t_pm"], 40)
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_INITIATOR))
        t_pm.setCurrentIndex(t_pm.findData(20))
        mode.setCurrentIndex(mode.findData(1))
        self.assertFalse(t_pm.isEnabled())
        self.assertEqual(w.host_settings["t_pm"], 40)

    def test_cs_modes_labels_controls_and_options_have_tooltips(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QComboBox, QSpinBox
        from ble_channel_sounding.views.cs_view import CS_CONTROL_HELP
        w = self.window
        w.settings.setCurrentIndex(1)
        form = w.settings.widget(1).widget().layout()
        # Plus the Reflector data and Preferred T_PM host settings below IPT and the example panel.
        self.assertEqual(form.rowCount() - 3, len(CS_CONTROL_HELP))
        ipt_row, _ = form.getWidgetPosition(w.controls["configuration.cs_enhancements_1"])
        for offset, name, label in ((1, "peer_data", "Reflector data"), (2, "t_pm", "Preferred T_PM")):
            control = form.itemAt(ipt_row + offset, form.ItemRole.FieldRole).widget()
            self.assertIs(control, w.host_controls[name])
            self.assertEqual(form.labelForField(control).text(), label)
            self.assertTrue(control.toolTip())
        for key in CS_CONTROL_HELP:
            control = w.controls[key]
            self.assertTrue(control.toolTip(), key)
            self.assertEqual(form.labelForField(control).toolTip(), control.toolTip())
            if isinstance(control, QSpinBox):
                self.assertEqual(control.lineEdit().toolTip(), control.toolTip())
            if isinstance(control, QComboBox):
                for i in range(control.count()):
                    tip = control.itemData(i, Qt.ItemDataRole.ToolTipRole)
                    self.assertIn(control.itemText(i), tip)
                    self.assertIn(control.toolTip(), tip)

    def assert_tab_tooltips(self, title, help_texts, controls):
        """Every row of a settings tab shows its help on the label, control and combo options."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QComboBox, QSpinBox
        w = self.window
        index = next(i for i in range(w.settings.count()) if w.settings.tabText(i) == title)
        form = w.settings.widget(index).widget().layout()
        labeled = [form.itemAt(row, form.ItemRole.FieldRole) for row in range(form.rowCount())]
        self.assertEqual(sum(1 for item in labeled if item and form.labelForField(item.widget())), len(help_texts))
        for key, text in help_texts.items():
            control = controls[key]
            self.assertEqual(control.toolTip(), text, key)
            self.assertEqual(form.labelForField(control).toolTip(), text, key)
            if isinstance(control, QSpinBox):
                self.assertEqual(control.lineEdit().toolTip(), text, key)
            if isinstance(control, QComboBox):
                for i in range(control.count()):
                    tip = control.itemData(i, Qt.ItemDataRole.ToolTipRole)
                    self.assertIn(control.itemText(i), tip)
                    self.assertIn(text, tip)

    def test_schedule_and_host_labels_controls_and_options_have_tooltips(self):
        from ble_channel_sounding.views.cs_view import SCHEDULE_CONTROL_HELP, HOST_CONTROL_HELP
        w = self.window
        self.assert_tab_tooltips("Schedule", SCHEDULE_CONTROL_HELP, w.controls)
        # Reflector data and Preferred T_PM are host settings shown on the CS modes tab, below IPT.
        host_help = {key: tip for key, tip in HOST_CONTROL_HELP.items() if key not in ("peer_data", "t_pm")}
        self.assert_tab_tooltips("Host", host_help, {**w.host_controls, "peripheral_patterns": w.patterns})

    def test_every_setting_has_a_tooltip_and_a_detailed_help_entry(self):
        from ble_channel_sounding.views.control_help import CONTROL_DETAILS, detail_html
        w = self.window
        controls = {**w.controls, **w.host_controls, "peripheral_patterns": w.patterns}
        self.assertEqual(set(w.help_rows), set(controls))
        self.assertEqual(set(CONTROL_DETAILS), set(controls))
        for key, control in controls.items():
            label, tip, registered = w.help_rows[key]
            self.assertIs(registered, control, key)
            self.assertTrue(tip, key)
            self.assertEqual(control.toolTip(), tip, key)
            detail = CONTROL_DETAILS[key]
            self.assertTrue(detail.defines.startswith(("This setting defines ", "This example value represents ")), key)
            self.assertTrue(detail.standard and detail.effect, key)
            html = detail_html(key, label, tip)
            for part in (tip, detail.defines_heading, "Where the standard defines it", "Effect of a change"):
                self.assertIn(escape(part), html, key)
            if detail.selection:
                self.assertIn("How the value is selected", html, key)
                self.assertIn(escape(detail.selection), html, key)
            self.assertGreater(html.rfind("Where the standard defines it"), html.rfind("Effect of a change"), key)

    def test_help_pane_shows_tab_overview_and_selected_or_hovered_setting(self):
        from PyQt6 import QtCore, QtGui
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.views.control_help import TAB_HELP
        w = self.window
        self.assertTrue({w.settings.tabText(i) for i in range(w.settings.count())} <= set(TAB_HELP))
        for index in range(w.settings.count()):
            w.settings.setCurrentIndex(index)
            title = w.settings.tabText(index)
            self.assertIs(w.help_pane.currentWidget(), w.tab_help)
            text = w.tab_help.toPlainText()
            self.assertIn(TAB_HELP[title][0], text)
            page = w.settings.widget(index)
            for key, (label, _, control) in w.help_rows.items():
                if page.isAncestorOf(control):
                    self.assertIn(label, text, key)
        w.settings.setCurrentIndex(2)
        control = w.controls["procedure.subevent_len"]
        control.setFocus(QtCore.Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        self.assertIs(w.help_pane.currentWidget(), w.setting_help)
        self.assertIn("Min_Subevent_Len", w.setting_help.toPlainText())
        w.settings.setCurrentIndex(0)  # focus leaves the hidden control without selecting another
        self.app.processEvents()
        self.assertIs(w.help_pane.currentWidget(), w.tab_help)
        target = w.controls["connection.latency"]
        QtCore.QCoreApplication.sendEvent(target, QtGui.QEnterEvent(QtCore.QPointF(2, 2), QtCore.QPointF(2, 2), QtCore.QPointF(2, 2)))
        self.assertIs(w.help_pane.currentWidget(), w.tab_help)  # a pointer passing over does not switch
        QTest.qWait(500)
        self.assertIs(w.help_pane.currentWidget(), w.setting_help)
        self.assertIn("Max_Latency", w.setting_help.toPlainText())
        w.tab_help.anchorClicked.emit(QtCore.QUrl("#configuration.ch3c_jump"))
        text = w.setting_help.toPlainText()
        self.assertIn("Ch3c_Jump", text)
        self.assertIn("Currently read-only", text)  # CSA #3b holds the #3c jump

    def test_example_values_sit_in_a_panel_on_their_own_tab(self):
        from ble_channel_sounding.planner.model import EXAMPLE_FIELDS
        from ble_channel_sounding.views.control_help import TIMING_MANDATORY_VALUES
        from ble_channel_sounding.views.cs_view import EXAMPLE_CONTROL_HELP
        w = self.window
        self.assertEqual(set(EXAMPLE_CONTROL_HELP), set(EXAMPLE_FIELDS))
        self.assertEqual([w.settings.tabText(i) for i in range(w.settings.count())],
                         ["Connection", "CS modes", "Schedule", "Channels", "Host"])
        tabs = {"Connection": ("connection.interval", "connection.activity_us", "connection.mtu", "event_offset_us"),
                "CS modes": ("main_steps", "configuration.t_ip1_time_us", "configuration.t_ip2_time_us",
                             "configuration.t_fcs_time_us", "configuration.t_pm_time_us", "t_sw_us", "t_sw_ipt_us"),
                "Schedule": ("target_steps", "procedure.subevents_per_event", "procedure.subevent_interval",
                             "procedure.event_interval", "preview_count"),
                "Channels": ("channel_seed",)}
        self.assertEqual({key for keys in tabs.values() for key in keys}, set(EXAMPLE_FIELDS))
        self.assertEqual(len(w.example_panels), len(tabs))
        for title, keys in tabs.items():
            page = next(w.settings.widget(i) for i in range(w.settings.count()) if w.settings.tabText(i) == title)
            panel = next(box for box in w.example_panels if page.isAncestorOf(box))
            self.assertEqual(panel.title(), "Example config values selected by the controller")
            self.assertIn("At runtime, T_IP1, T_IP2, T_FCS and T_PM are selected during the Channel Sounding Configuration procedure", panel.toolTip())
            self.assertIn("Possible values are T_IP1/T_IP2 = 10, 20, 30, 40, 50, 60, 80 or 145 µs", panel.toolTip())
            form = panel.layout()
            self.assertEqual(form.rowCount(), len(keys), title)
            for key in keys:
                control = w.controls[key]
                self.assertIs(control.parentWidget(), panel, key)
                self.assertEqual(control.toolTip(), EXAMPLE_CONTROL_HELP[key], key)
                self.assertEqual(form.labelForField(control).toolTip(), control.toolTip(), key)
                self.assertIn("not sent", control.toolTip(), key)
                if key in TIMING_MANDATORY_VALUES:
                    mandatory = TIMING_MANDATORY_VALUES[key]
                    self.assertIn("(mandatory)", control.itemText(control.findData(int(mandatory.split()[0]))), key)

    def test_ipt_channel_selection_subevents_and_role_hold_unused_controls(self):
        from ble_channel_sounding.planner.model import Scenario
        from ble_channel_sounding.protocol.packets import OperationMode
        w = self.window
        default = Scenario()
        ipt = w.controls["configuration.cs_enhancements_1"]
        ipt.setCurrentIndex(ipt.findData(1))
        self.assertFalse(w.controls["t_sw_us"].isEnabled())
        w.set_control_value(w.controls["t_sw_ipt_us"], 10)
        ipt.setCurrentIndex(ipt.findData(0))
        self.assertFalse(w.controls["t_sw_ipt_us"].isEnabled())
        self.assertEqual(w.controls["t_sw_ipt_us"].currentData(), default.t_sw_ipt_us)
        self.assertTrue(w.controls["t_sw_us"].isEnabled())

        w.controls["procedure.subevents_per_event"].setValue(1)
        self.assertFalse(w.controls["procedure.subevent_interval"].isEnabled())
        self.assertEqual(w.controls["procedure.subevent_interval"].value(), 0)
        w.controls["procedure.subevents_per_event"].setValue(2)
        self.assertTrue(w.controls["procedure.subevent_interval"].isEnabled())

        w.set_control_value(w.host_controls["creation_context"], 0)
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_REFLECTOR))
        self.assertFalse(w.host_controls["creation_context"].isEnabled())
        self.assertEqual(w.host_settings["creation_context"], 1)
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_INITIATOR))
        self.assertTrue(w.host_controls["creation_context"].isEnabled())

    def test_preferred_peer_antenna_check_boxes_set_the_mask(self):
        from ble_channel_sounding.protocol.packets import OperationMode
        w = self.window
        mode, control = w.controls["configuration.mode"], w.host_controls["preferred_peer_antenna"]
        mode.setCurrentIndex(mode.findData(2))  # PBR only
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_INITIATOR))
        w.set_control_value(w.controls["procedure.tone_antenna_config_selection"], 5)  # A1:B3
        w.set_control_value(control, 1)
        self.assertIn("set at least 3", control.summary.text())
        control.boxes[1].click()
        self.assertEqual(w.host_settings["preferred_peer_antenna"], 3)
        self.assertEqual([box.isChecked() for box in control.boxes], [True, True, False, False])
        self.assertIn("set at least 3", control.summary.text())
        control.boxes[3].click()
        self.assertEqual(w.host_settings["preferred_peer_antenna"], 0x0B)
        self.assertEqual(control.summary.text(), "0x0b")
        # A reflector's peer side is A: one initiator antenna is enough.
        w.set_control_value(control, 1)
        w.target_mode.setCurrentIndex(w.target_mode.findData(OperationMode.CS_REFLECTOR))
        self.assertEqual(control.summary.text(), "0x01")
        # Bits above antenna 4 in a loaded mask stay for validation to report.
        w.set_control_value(control, 0x13)
        self.assertEqual([box.isChecked() for box in control.boxes], [True, True, False, False])
        control.boxes[2].click()
        self.assertEqual(w.host_settings["preferred_peer_antenna"], 0x17)

    def test_mode_without_sub_mode_rtt_or_pbr_holds_those_fields_at_defaults(self):
        from ble_channel_sounding.planner.model import (PBR_FIELDS, PBR_HOST_FIELDS, RTT_FIELDS, RTT_HOST_FIELDS, SUB_MODE_FIELDS,
                                 Scenario, scenario_value)
        w = self.window
        default = Scenario()
        mode = w.controls["configuration.mode"]
        mode.setCurrentIndex(mode.findData(0x12))
        for key, value in (("configuration.min_main_mode_steps", 6), ("configuration.max_main_mode_steps", 9),
                           ("main_steps", 7), ("configuration.t_pm_time_us", 40), ("t_sw_us", 10)):
            w.set_control_value(w.controls[key], value)
        w.set_control_value(w.controls["configuration.rtt_type"], 3)
        w.set_control_value(w.host_controls["snr_control_initiator"], 2)
        w.set_control_value(w.host_controls["preferred_peer_antenna"], 3)
        self.assertTrue(all(w.controls[key].isEnabled() for key in SUB_MODE_FIELDS + RTT_FIELDS))

        mode.setCurrentIndex(mode.findData(1))  # RTT only
        for key in SUB_MODE_FIELDS + PBR_FIELDS:
            control = w.controls[key]
            self.assertFalse(control.isEnabled(), key)
            value = control.currentData() if hasattr(control, "currentData") else control.value()
            self.assertEqual(value, scenario_value(default, key), key)
        self.assertTrue(w.controls["configuration.rtt_type"].isEnabled())
        self.assertEqual(w.controls["configuration.rtt_type"].currentData(), 3)
        self.assertFalse(w.host_controls["preferred_peer_antenna"].isEnabled())
        self.assertEqual(w.host_settings["preferred_peer_antenna"], 1)
        self.assertTrue(w.host_controls["snr_control_initiator"].isEnabled())

        mode.setCurrentIndex(mode.findData(2))  # PBR only
        self.assertFalse(w.controls["configuration.rtt_type"].isEnabled())
        self.assertEqual(w.controls["configuration.rtt_type"].currentData(), 0)
        for name in RTT_HOST_FIELDS:
            self.assertFalse(w.host_controls[name].isEnabled(), name)
            self.assertEqual(w.host_settings[name], 0xFF)
        self.assertTrue(all(w.controls[key].isEnabled() for key in PBR_FIELDS if key != "t_sw_ipt_us"))
        self.assertTrue(all(w.host_controls[name].isEnabled() for name in PBR_HOST_FIELDS))

        # A loaded plan shows the defaults too.
        w.scenario = replace(default, configuration=replace(default.configuration, mode=1, t_pm_time_us=40))
        w.populate()
        self.assertEqual(w.scenario.configuration.t_pm_time_us, default.configuration.t_pm_time_us)
        self.assertEqual(w.controls["configuration.t_pm_time_us"].currentData(), default.configuration.t_pm_time_us)
        self.assertEqual(w.read_controls(), w.scenario)

    def test_tooltips_wrap_at_half_the_main_window_width(self):
        import re
        from PyQt6.QtCore import QEvent, QPoint
        from PyQt6.QtGui import QHelpEvent
        from PyQt6.QtWidgets import QToolTip
        from ble_channel_sounding.views.tooltips import fit_tooltip, install
        w = self.window
        w.resize(1200, 700)
        self.app.processEvents()
        self.assertEqual(fit_tooltip("Short", w), "<qt>Short</qt>")
        self.assertEqual(fit_tooltip("a < b\nc", w), "<qt>a &lt; b<br>c</qt>")
        long_text = w.controls["procedure.procedure_interval"].toolTip()
        wrapped = fit_tooltip(long_text, w.controls["procedure.procedure_interval"])
        self.assertEqual(int(re.search(r'width="(\d+)"', wrapped).group(1)), w.width() // 2)
        tooltip_filter = install(self.app)
        try:
            for key in ("procedure.procedure_interval", "configuration.mode", "t_sw_us"):
                control = w.controls[key]
                QToolTip.hideText()
                self.app.sendEvent(control, QHelpEvent(QEvent.Type.ToolTip, QPoint(2, 2), control.mapToGlobal(QPoint(2, 2))))
                self.assertIn("<table width=", QToolTip.text())
                label = next(top for top in self.app.topLevelWidgets()
                             if top.objectName() == "qtooltip_label" and top.isVisible())
                self.assertLessEqual(label.width(), w.width() // 2, key)
        finally:
            self.app.removeEventFilter(tooltip_filter)
            QToolTip.hideText()

    def test_tooltips_ignore_qt_created_header_views(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QHeaderView, QTableWidget
        from ble_channel_sounding.views.tooltips import TooltipWidthFilter
        table = QTableWidget(1, 1)
        table.show()
        self.app.processEvents()
        try:
            for header in table.findChildren(QHeaderView):
                self.assertIsNone(TooltipWidthFilter.text_at(header.viewport(), QPoint(1, 1)))
        finally:
            table.close()
            table.deleteLater()
            self.app.processEvents()

    def test_cs_mode_tooltip_is_visible_on_hover(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QToolTip
        w = self.window
        w.settings.setCurrentIndex(1)
        w.activateWindow()
        self.app.processEvents()
        control = w.controls["configuration.mode"]
        QToolTip.hideText()
        QTest.mouseMove(control, control.rect().center())
        QTest.qWait(1200)
        self.assertTrue(QToolTip.isVisible())
        self.assertIn("Mode 1 uses RTT", QToolTip.text())
        QToolTip.hideText()

    def test_mouse_click_on_step_opens_detail(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.views.cs_view import Block
        w = self.window
        w.views.setCurrentIndex(2)
        self.app.processEvents()
        block = next(item for item in w.event_plot.items()
                     if isinstance(item, Block) and "Step 3 ·" in item.toolTip())
        point = w.event_plot.mapFromScene(block.mapToScene(block.rect.center()))
        QTest.mouseClick(w.event_plot.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        self.assertEqual(w.views.currentIndex(), 3)
        self.assertEqual(w.step_select.currentData(), 2)

    def test_later_procedure_event_and_step_use_shared_time_origin(self):
        from dataclasses import replace
        w = self.window
        # Keep this exact timing example on a four-path A4:B1 setup with enough
        # budget and procedure spacing for the mandatory timing defaults.
        scenario = replace(w.scenario, procedure=replace(
            w.scenario.procedure, tone_antenna_config_selection=3,
            max_procedure_len=700, procedure_interval=14))
        w.apply_config(scenario)
        w.select_event(1, procedure=2)
        self.assertEqual(w.procedure_select.currentData(), 2)
        origin = w.procedure_start
        event_subevents = [se for se in w.schedule.subevents if se.event == 1]
        event_start = origin + event_subevents[0].start
        event_end = origin + event_subevents[-1].start + event_subevents[-1].duration
        for value, expected in zip(w.event_plot.viewRange()[0], (event_start / 1000, event_end / 1000)):
            self.assertAlmostEqual(value, expected)
        self.assertEqual(w.event_plot.getAxis("bottom").bounds, (event_start / 1000, event_end / 1000))
        se = w.schedule.subevents[2]
        w.select_subevent(se.index)
        subevent_start = origin + se.start
        subevent_end = subevent_start + se.duration
        for value, expected in zip(w.event_plot.viewRange()[0], (subevent_start / 1000, subevent_end / 1000)):
            self.assertAlmostEqual(value, expected)
        step = se.steps[2]
        w.select_step(se.index, step.index)
        step_start = origin + step.start
        step_end = step_start + step.duration
        for value, expected in zip(w.step_plot.viewRange()[0], (step_start, step_end)):
            self.assertAlmostEqual(value, expected)
        self.assertIn(f"Start {step_start} µs", w.step_info.text())
        self.assertIn(f"End {step_end} µs", w.step_info.text())
        self.assertIn("outside this step", w.step_info.text())
        # Edge labels must actually be drawn, not just exist as tick values.
        from PyQt6.QtGui import QImage, QPainter
        surface = QImage(1200, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(surface)
        axis = w.step_plot.getAxis("bottom")
        try:
            _, _, specs = axis.generateDrawSpecs(painter)
        finally:
            painter.end()
        labels = {text: rect for rect, _, text in specs}
        area = axis.mapRectFromParent(axis.geometry())
        for text in (str(step_start), str(step_end)):
            self.assertIn(text, labels)
            self.assertGreaterEqual(labels[text].left(), area.left())
            self.assertLessEqual(labels[text].right(), area.right())

    def test_clicking_later_event_retains_its_procedure(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.views.cs_view import Block
        w = self.window
        w.views.setCurrentIndex(1)
        self.app.processEvents()
        block = next(item for item in w.procedure_plot.items()
                     if isinstance(item, Block) and "Procedure 3, CS event 2:" in item.toolTip())
        point = w.procedure_plot.mapFromScene(block.mapToScene(block.rect.center()))
        QTest.mouseClick(w.procedure_plot.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        self.assertEqual(w.views.currentIndex(), 2)
        self.assertEqual(w.procedure_select.currentData(), 2)
        self.assertEqual(w.event_select.currentData(), 1)
        self.assertIn("Procedure 3", w.event_info.text())

    def test_all_boxes_have_timing_tooltips_and_hover_displays_them(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QToolTip
        from ble_channel_sounding.views.cs_view import Block
        w = self.window
        for plot in (w.connection_plot, w.timeout_plot, w.procedure_plot, w.event_plot, w.step_plot):
            boxes = [item for item in plot.items() if isinstance(item, Block)]
            self.assertTrue(boxes)
            for block in boxes:
                for text in ("Start:", "End:", "Duration:", "Time origin:"):
                    self.assertIn(text, block.toolTip())
        w.select_step(0, 2)
        self.app.processEvents()
        block = next(item for item in w.step_plot.items() if isinstance(item, Block) and item.label == "T_IP2")
        point = w.step_plot.mapFromScene(block.mapToScene(block.rect.center()))
        QTest.mouseMove(w.step_plot.viewport(), point)
        QTest.qWait(150)
        self.assertTrue(QToolTip.isVisible())
        self.assertIn("Interlude", QToolTip.text())
        self.assertIn("Start:", QToolTip.text())
        QToolTip.hideText()

    def test_ras_transfer_is_drawn_from_the_reported_or_default_mtu(self):
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.views.cs_view import Block
        from ble_channel_sounding.protocol.packets import ConnectionParametersPacket
        w = self.window

        def ras_blocks(plot):
            return [item for item in plot.items() if isinstance(item, Block) and item.label == "RAS"]

        self.assertEqual(w.connection_plot.rows[3], "RAS (reflector)")
        self.assertEqual(w.procedure_plot.rows[3], "RAS (reflector)")
        # Before an MTU exchange is reported the ATT default sizes the transfer.
        self.assertFalse(w.reported_mtu())
        self.assertEqual(w.controls["connection.mtu"].value(), 23)
        self.assertEqual(w.schedule.ras.mtu, 23)
        self.assertTrue(ras_blocks(w.connection_plot))
        self.assertEqual(len(ras_blocks(w.procedure_plot)), w.procedure_select.count() * w.schedule.ras.events)
        for text in ("RAS real-time from ACL event", "ATT MTU 23 (ATT default; no MTU exchange reported)",
                     "38 LL PDU(s)", "LE 1M air time", "Occupancy, not a predicted drain rate"):
            self.assertIn(text, w.connection_info.text())
            self.assertIn(text.replace("RAS real-time from ACL event", "RAS real-time from ACL event"),
                          w.procedure_info.text())
        self.assertIn("air time", ras_blocks(w.connection_plot)[0].toolTip())
        # A reported MTU segments the same ranging data into fewer notifications.
        w.apply_config(ConnectionParametersPacket(interval=24, latency=0, timeout=400, mtu=498))
        self.app.processEvents()
        self.assertTrue(w.reported_mtu())
        self.assertEqual(w.controls["connection.mtu"].value(), 498)
        self.assertEqual(w.schedule.ras.notifications, 2)
        self.assertLess(w.schedule.ras.airtime_us, 25688)
        self.assertIn("ATT MTU 498 (reported by the client)", w.connection_info.text())
        # Editing the field explores another MTU, and says it is not the reported one.
        w.controls["connection.mtu"].setValue(247)
        QTest.qWait(150)
        self.assertEqual(w.scenario.connection.mtu, 247)
        self.assertIn("ATT MTU 247 (example value; not reported)", w.connection_info.text())
        w.controls["connection.mtu"].setValue(498)
        QTest.qWait(150)
        # The configured ACL PHY sets the air time.
        before = w.schedule.ras.airtime_us
        w.host_controls["phy"].setCurrentIndex(w.host_controls["phy"].findData(2))
        QTest.qWait(150)
        self.assertLess(w.schedule.ras.airtime_us, before)
        self.assertIn("LE 2M air time", w.connection_info.text())
        # Initiator-only data has no RAS transfer to draw.
        w.controls["configuration.cs_enhancements_1"].setCurrentIndex(
            w.controls["configuration.cs_enhancements_1"].findData(1))
        w.host_controls["peer_data"].setCurrentIndex(w.host_controls["peer_data"].findData(1))
        QTest.qWait(150)
        self.assertIsNone(w.schedule.ras)
        self.assertEqual(ras_blocks(w.connection_plot) + ras_blocks(w.procedure_plot), [])
        self.assertIn("initiator only (IPT) — no RAS notifications", w.connection_info.text())

    def test_connection_preview_count_is_limited_by_visible_anchor_window(self):
        from dataclasses import replace
        w = self.window
        scenario = replace(
            w.scenario,
            preview_count=10,
            procedure=replace(w.scenario.procedure, procedure_interval=5),
        )
        w.apply_config(scenario)

        # Twelve 30 ms anchors and a 150 ms procedure spacing leave three
        # procedure starts visible, even though ten were requested.
        self.assertIn("3 of 10 preview instance(s) start within the 12 anchors shown", w.connection_info.text())

        scenario = replace(w.scenario, event_offset_us=12 * w.scenario.connection.interval_us)
        w.apply_config(scenario)
        self.assertIn("0 of 10 preview instance(s) start within the 12 anchors shown", w.connection_info.text())

    def test_channel_map_editor_and_view_update_scenario(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ble_channel_sounding.views.cs_view import Block
        from ble_channel_sounding.planner.model import channel_map_bytes, enabled_channels
        w = self.window
        editor = w.controls["configuration.channel_map"]
        self.assertEqual(editor.summary.text(), "72 of 72 channels enabled")
        self.assertFalse(editor.buttons[24].isEnabled())
        editor.buttons[2].click()
        QTest.qWait(150)
        self.assertNotIn(2, enabled_channels(w.scenario.configuration.channel_map))
        self.assertIn("71 of 72 channels enabled", w.channel_info.text())
        self.assertIn("depends on the CS DRBG state", w.channel_info.text())
        self.assertNotIn(2, [st.channel for se in w.schedule.subevents for st in se.steps])
        # Clicking a channel in the spectrum view toggles it back.
        w.views.setCurrentIndex(4)
        self.app.processEvents()
        block = next(item for item in w.channel_plot.items()
                     if isinstance(item, Block) and "Channel 2 ·" in item.toolTip())
        point = w.channel_plot.mapFromScene(block.mapToScene(block.rect.center()))
        QTest.mouseClick(w.channel_plot.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(150)
        self.assertIn(2, enabled_channels(w.scenario.configuration.channel_map))
        # Hex entry applies only complete 10-byte maps.
        editor.hex.setText("abc")
        editor.hex.editingFinished.emit()
        QTest.qWait(150)
        self.assertEqual(len(w.scenario.configuration.channel_map), 10)
        editor.hex.setText(channel_map_bytes(range(2, 16)).hex())
        editor.hex.editingFinished.emit()
        QTest.qWait(150)
        self.assertTrue(any("currently 14" in e for e in w.schedule.errors))

    def test_hop_plot_markers_have_tips_and_open_step(self):
        import pyqtgraph as pg
        w = self.window
        scatters = [item for item in w.hop_plot.items() if isinstance(item, pg.ScatterPlotItem)]
        points = [point for item in scatters for point in item.points()]
        self.assertEqual(len(points), sum(len(se.steps) for se in w.schedule.subevents))
        point = next(p for p in points if p.data() == (1, w.schedule.subevents[1].steps[3].index))
        step = w.schedule.subevents[1].steps[3]
        self.assertEqual(point.pos().y(), step.channel)
        self.assertIn("depends on CS DRBG state", w.hop_tip(0, 0, point.data()))
        w.hop_clicked(None, [point])
        self.assertEqual(w.views.currentIndex(), 3)
        self.assertEqual(w.step_select.currentData(), step.index)
        self.assertIn(f"example channel {step.channel}", w.step_info.text())
        w.controls["channel_seed"].setValue(7)
        from PyQt6.QtTest import QTest
        QTest.qWait(150)
        self.assertIn("seed 7", w.channel_info.text())

    def test_csa3c_fields_enable_only_for_3c_and_round_trip(self):
        from dataclasses import replace
        from PyQt6.QtTest import QTest
        w = self.window
        self.assertFalse(w.controls["configuration.ch3c_jump"].isEnabled())
        selection = w.controls["configuration.channel_selection_type"]
        selection.setCurrentIndex(selection.findData(1))
        self.assertTrue(w.controls["configuration.ch3c_jump"].isEnabled())
        QTest.qWait(150)
        self.assertEqual(w.scenario.configuration.channel_selection_type, 1)
        self.assertIn("CSA #3c, Hat shape, jump 2", w.channel_info.text())
        w.set_control_value(w.controls["configuration.ch3c_jump"], 4)
        # A #3b report shows the unused #3c fields at their defaults, read-only.
        config = replace(w.scenario.configuration, channel_selection_type=0, ch3c_jump=0)
        w.apply_controller_packets(config, w.scenario.procedure)
        self.assertEqual(w.read_controls().configuration, replace(config, ch3c_jump=2))
        self.assertFalse(w.controls["configuration.ch3c_jump"].isEnabled())

    def test_errors_display_calculated_corrections(self):
        from PyQt6.QtTest import QTest
        w = self.window
        w.controls["procedure.subevent_interval"].setValue(1)
        QTest.qWait(150)
        text = w.details.toPlainText()
        self.assertIn("What to correct:", text)
        self.assertIn("at least 9 × 625 µs", text)
        w.reset()
        w.controls["procedure.max_procedure_len"].setValue(10)
        QTest.qWait(150)
        text = w.details.toPlainText()
        self.assertIn("What to correct:", text)
        self.assertIn("Increase Procedure budget to at least 14 × 625 µs", text)


if __name__ == "__main__":
    unittest.main()
