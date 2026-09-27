import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
import unittest

from PyQt6 import QtCore, QtWidgets as W

from cs_app.views.help_dialog import HELP_PAGES, HelpDialog
from cs_app.views.run_bar import ACTIONS, RunBar


class HelpDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def test_opens_on_the_overview_of_purpose_and_capabilities(self):
        dialog = HelpDialog()
        try:
            self.assertEqual(dialog.topics.currentItem().text(), "About CS Host")
            text = dialog.browser.toPlainText()
            self.assertIn("What you can do with CS Host", text)
            self.assertIn("Channel Sounding", text)
        finally:
            dialog.deleteLater()

    def test_topic_links_resolve_and_switch_pages(self):
        keys = {key for key, _, _ in HELP_PAGES}
        for key, _, body in HELP_PAGES:
            for target in re.findall(r'href="help:([^"]+)"', body):
                with self.subTest(page=key, link=target):
                    self.assertIn(target, keys)
        dialog = HelpDialog()
        try:
            dialog.follow_link(QtCore.QUrl("help:results"))
            self.assertEqual(dialog.topics.currentItem().text(), "Reading results")
        finally:
            dialog.deleteLater()

    def test_toolbar_topic_names_every_session_action(self):
        body = dict((key, body) for key, _, body in HELP_PAGES)["toolbar"]
        labels = [RunBar.CONNECTION_STATES["disconnected"][0] if name == "Connect" else name
                  for name in ACTIONS]
        for label in labels:
            with self.subTest(action=label):
                self.assertIn(f"<b>{label}</b>", body)


if __name__ == '__main__':
    unittest.main()
