"""Standalone ble_channel_sounding_planner window, offscreen: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_cs_planner_gui"""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from html import escape

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = all(importlib.util.find_spec(m) for m in ("PyQt6", "pyqtgraph"))
PLAN_FIXTURE = Path(__file__).resolve().parent / "data" / "cs-plan.json"


@unittest.skipUnless(GUI_AVAILABLE, "Install PyQt6 and pyqtgraph for Qt checks")
class StandalonePlannerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ble_channel_sounding_planner.view import PlannerWidget
        self.window = PlannerWidget()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait(self):
        from PyQt6.QtTest import QTest
        QTest.qWait(150)

    def test_five_views_render_and_navigation_drills_down(self):
        w = self.window
        w.apply_scenario(replace(w.scenario, target_steps=20))
        self.assertEqual(w.views.count(), 5)
        self.assertEqual(w.settings.count(), 5)  # Connection, CS modes, Schedule, Channels, Host
        self.assertTrue(w.schedule.complete)
        se = w.schedule.subevents[-1]
        w.select_step(se.index, se.steps[-1].index)
        self.assertEqual(w.views.currentIndex(), 3)
        self.assertEqual(w.event_select.currentData(), se.event)
        self.assertEqual(w.subevent_select.currentData(), se.index)
        self.assertIn("Mode 2", w.step_info.text())
        with tempfile.TemporaryDirectory() as directory:
            for i in range(w.views.count()):
                w.views.setCurrentIndex(i)
                self.app.processEvents()
                file = Path(directory) / f"view-{i}.png"
                self.assertTrue(w.views.currentWidget().grab().save(str(file)))
                self.assertGreater(file.stat().st_size, 1000)

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
        from ble_channel_sounding_planner.view import SCHEDULE_CONTROL_HELP, HOST_CONTROL_HELP
        w = self.window
        self.assert_tab_tooltips("Schedule", SCHEDULE_CONTROL_HELP, w.controls)
        self.assert_tab_tooltips("Host", HOST_CONTROL_HELP, {**w.host_controls, "peripheral_patterns": w.patterns, "device_name": w.device_name})
        from ble_channel_sounding_planner.view import EXAMPLE_CONTROL_HELP
        from ble_channel_sounding_planner.control_help import TIMING_MANDATORY_VALUES
        self.assertEqual(len(w.example_panels), 4)
        for panel in w.example_panels:
            self.assertIn("At runtime, T_IP1, T_IP2, T_FCS and T_PM are selected during the Channel Sounding Configuration procedure", panel.toolTip())
            self.assertIn("Possible values are T_IP1/T_IP2 = 10, 20, 30, 40, 50, 60, 80 or 145 µs", panel.toolTip())
        for key, text in EXAMPLE_CONTROL_HELP.items():
            self.assertIn(w.controls[key].parentWidget(), w.example_panels, key)
            self.assertEqual(w.controls[key].toolTip(), text, key)
            if key in TIMING_MANDATORY_VALUES:
                mandatory = TIMING_MANDATORY_VALUES[key]
                self.assertIn("(mandatory)", w.controls[key].itemText(w.controls[key].findData(int(mandatory.split()[0]))), key)

    def test_every_setting_has_a_tooltip_and_a_detailed_help_entry(self):
        from ble_channel_sounding_planner.control_help import CONTROL_DETAILS, detail_html
        w = self.window
        controls = {**w.controls, **w.host_controls, "peripheral_patterns": w.patterns, "device_name": w.device_name}
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
        from ble_channel_sounding_planner.control_help import TAB_HELP
        w = self.window
        self.assertEqual(set(TAB_HELP), {w.settings.tabText(i) for i in range(w.settings.count())})
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

    def test_help_entries_match_cs_app_except_the_bluetooth_name(self):
        import ble_channel_sounding.views.control_help as app_help
        import ble_channel_sounding_planner.control_help as planner_help
        # The reference PHY also reads as the assumed ACL PHY in ble-channel-sounding, where it sizes the RAS
        # real-time transfer the standalone planner has no reflector-data setting to draw (§13.5).
        app_only = ("peer_data", "t_pm", "phy", "connection.mtu")
        self.assertEqual({k: v for k, v in planner_help.CONTROL_DETAILS.items()
                          if k not in ("device_name", "phy")},
                         {k: v for k, v in app_help.CONTROL_DETAILS.items() if k not in app_only})
        for name in ("CONNECTION_CONTROL_HELP", "CS_CONTROL_HELP", "CHANNEL_CONTROL_HELP", "SCHEDULE_CONTROL_HELP", "EXAMPLE_CONTROL_HELP"):
            # The example T_PM differs: only ble-channel-sounding has the Preferred T_PM client setting to point at.
            skip = ("configuration.t_pm_time_us",) if name == "EXAMPLE_CONTROL_HELP" else ()
            self.assertEqual({k: v for k, v in getattr(planner_help, name).items() if k not in skip},
                             {k: v for k, v in getattr(app_help, name).items() if k not in skip + app_only}, name)
        self.assertEqual({k: v for k, v in planner_help.HOST_CONTROL_HELP.items()
                          if k not in ("device_name", "phy")},
                         {k: v for k, v in app_help.HOST_CONTROL_HELP.items() if k not in app_only})

    def test_preferred_peer_antenna_check_boxes_set_the_mask(self):
        w = self.window
        mode, control = w.controls["configuration.mode"], w.host_controls["preferred_peer_antenna"]
        mode.setCurrentIndex(mode.findData(2))  # PBR only
        w.target_mode.setCurrentIndex(w.target_mode.findData(0))
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
        w.target_mode.setCurrentIndex(w.target_mode.findData(1))
        self.assertEqual(control.summary.text(), "0x01")
        # Bits above antenna 4 in a loaded mask stay for validation to report.
        w.set_control_value(control, 0x13)
        self.assertEqual([box.isChecked() for box in control.boxes], [True, True, False, False])
        control.boxes[2].click()
        self.assertEqual(w.host_settings["preferred_peer_antenna"], 0x17)

    def test_mode_without_sub_mode_rtt_or_pbr_holds_those_fields_at_defaults(self):
        from ble_channel_sounding_planner.model import (PBR_FIELDS, PBR_HOST_FIELDS, RTT_FIELDS, RTT_HOST_FIELDS, SUB_MODE_FIELDS,
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
        from ble_channel_sounding_planner.tooltips import fit_tooltip, install
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
        from ble_channel_sounding_planner.tooltips import TooltipWidthFilter
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

    def test_live_edit_recomputes_and_errors_show_corrections(self):
        w = self.window
        w.controls["target_steps"].setValue(20)
        self.wait()
        self.assertEqual(w.schedule.completed_steps, 20)
        w.controls["procedure.subevent_interval"].setValue(1)
        self.wait()
        self.assertTrue(w.schedule.errors)
        self.assertEqual(w.step_select.count(), 0)
        self.assertIn("No step available", w.step_info.text())
        self.assertIn("What to correct:", w.details.toPlainText())
        w.reset()
        self.assertEqual(w.scenario, w.read_controls())

    def test_open_and_save_keep_host_settings_and_role(self):
        from ble_channel_sounding_planner.model import loads
        w = self.window
        w.open_path(PLAN_FIXTURE)
        self.assertIn("cs-plan.json", w.source.text())
        self.assertEqual(w.host_settings["peripheral_patterns"], ["SW_CS_Reflector"])
        self.assertEqual(w.patterns.toPlainText(), "SW_CS_Reflector")
        w.target_mode.setCurrentIndex(w.target_mode.findData(1))
        editor = w.controls["configuration.channel_map"]
        editor.hex.setText("fcff7ffcffff00ffff1f")
        editor.hex.textEdited.emit(editor.hex.text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            with unittest.mock.patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                w.save_file()
            text = path.read_text(encoding="utf-8")
        s = loads(text)
        self.assertEqual(s.configuration.role, 1)
        self.assertEqual(s.configuration.channel_map.hex(), "fcff7ffcffff00ffff1f")
        self.assertEqual(json.loads(text)["host_settings"]["peripheral_patterns"], ["SW_CS_Reflector"])

    def test_opens_plan_embedded_in_c_export(self):
        from ble_channel_sounding_planner.export_c import MARKER as EXPORT_MARKER, document
        from ble_channel_sounding_planner.model import Scenario
        w = self.window
        s = Scenario()
        s = replace(s, configuration=replace(s.configuration, mode=3))
        source = f"int x;\n/* {EXPORT_MARKER}\n{document(s, {'gap_role': 1})}*/\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cs_generated_config.c"
            path.write_text(source, encoding="utf-8")
            w.open_path(path)
        self.assertEqual(w.controls["configuration.mode"].currentData(), 3)
        self.assertEqual(w.host_settings["gap_role"], 1)
        self.assertFalse(w.patterns.isEnabled())
        with self.assertRaises(ValueError):
            with tempfile.TemporaryDirectory() as directory:
                bad = Path(directory) / "bad.json"
                bad.write_text("[]", encoding="utf-8")
                w.open_path(bad)

    def test_export_c_writes_both_roles_with_host_tab_settings(self):
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        from ble_channel_sounding_planner.export_c import load_document
        w = self.window
        w.patterns.setPlainText("CS")
        w.device_name.setText("Tag")
        with tempfile.TemporaryDirectory() as directory, \
                unittest.mock.patch.object(QInputDialog, "getItem", return_value=("both", True)), \
                unittest.mock.patch.object(QFileDialog, "getExistingDirectory", return_value=directory):
            w.export_c()
            files = sorted(p.name for p in Path(directory).iterdir())
            source = (Path(directory) / "cs_generated_config_initiator.c").read_text(encoding="utf-8")
        self.assertEqual(files, ["cs_generated_config_initiator.c", "cs_generated_config_reflector.c"])
        self.assertIn('\\124\\141\\147', source)  # "Tag"
        self.assertEqual(load_document(source)[1]["peripheral_patterns"], ["CS"])

    def test_export_c_reports_errors(self):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        w = self.window
        w.patterns.setPlainText("")  # a central needs prefixes
        with unittest.mock.patch.object(QInputDialog, "getItem", return_value=("initiator", True)), \
                unittest.mock.patch.object(QMessageBox, "warning") as warning:
            w.export_c()
        self.assertIn("peripheral name prefixes", warning.call_args.args[2])

    def test_ipt_switches_tone_switch_control(self):
        w = self.window
        ipt = w.controls["configuration.cs_enhancements_1"]
        ipt.setCurrentIndex(ipt.findData(1))
        w.flush_edits()
        self.assertEqual(w.scenario.configuration.cs_enhancements_1, 1)
        self.assertTrue(w.controls["t_sw_ipt_us"].isEnabled())
        self.assertFalse(w.controls["t_sw_us"].isEnabled())

    def test_channel_map_editor_and_spectrum_click(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ble_channel_sounding_planner.channels import enabled_channels
        from ble_channel_sounding_planner.view import Block
        w = self.window
        editor = w.controls["configuration.channel_map"]
        self.assertEqual(editor.summary.text(), "72 of 72 channels enabled")
        editor.buttons[2].click()
        self.wait()
        self.assertNotIn(2, enabled_channels(w.scenario.configuration.channel_map))
        w.views.setCurrentIndex(4)
        self.app.processEvents()
        block = next(item for item in w.channel_plot.items()
                     if isinstance(item, Block) and "Channel 2 ·" in item.toolTip())
        point = w.channel_plot.mapFromScene(block.mapToScene(block.rect.center()))
        QTest.mouseClick(w.channel_plot.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.wait()
        self.assertIn(2, enabled_channels(w.scenario.configuration.channel_map))
        w.apply_channel_list(range(26, 54))
        self.assertIn("28 of 72 channels enabled", w.channel_info.text())

    def test_main_opens_window_with_file(self):
        from PyQt6.QtWidgets import QApplication
        from ble_channel_sounding_planner.__main__ import main
        sources = []

        def run():  # stands in for the event loop while the window exists
            window = next(widget for widget in QApplication.topLevelWidgets() if widget.windowTitle() == "CS Planner")
            sources.append(window.centralWidget().source.text())
            window.close()
            return 0

        with unittest.mock.patch.object(QApplication, "exec", side_effect=run):
            self.assertEqual(main([str(PLAN_FIXTURE)]), 0)
        self.assertIn("cs-plan.json", sources[0])


if __name__ == "__main__":
    unittest.main()
