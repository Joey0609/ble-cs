import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
import unittest
from pathlib import Path

from PyQt6 import QtCore, QtWidgets as W

from ble_channel_sounding.views import help_dialog
from ble_channel_sounding.views.help_dialog import HELP_PAGES, SCREENSHOTS, HelpDialog
from ble_channel_sounding.views.run_bar import ACTIONS, RunBar


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

    def test_screenshots_and_their_links_resolve(self):
        assets = Path(help_dialog.__file__).resolve().parent.parent / "assets" / "help"
        for key, _, body in HELP_PAGES:
            for image in re.findall(r'<img src="([^"]+)"', body):
                with self.subTest(page=key, image=image):
                    self.assertTrue((assets / image).is_file())
            for target in re.findall(r'href="screenshot:([^"]+)"', body):
                with self.subTest(page=key, screenshot=target):
                    self.assertIn(target, SCREENSHOTS)
        for key, (_, filename) in SCREENSHOTS.items():
            with self.subTest(screenshot=key):
                self.assertTrue((assets / filename).is_file())

    def test_images_follow_the_pane_width(self):
        dialog = HelpDialog(topic="configuration")
        try:
            dialog.show()
            widths = []
            for size in (900, 1400):
                dialog.resize(size, 800)
                self.app.processEvents()
                images = []
                block = dialog.browser.document().begin()
                while block.isValid():
                    fragments = block.begin()
                    while not fragments.atEnd():
                        form = fragments.fragment().charFormat()
                        if form.isImageFormat():
                            images.append(form.toImageFormat().width())
                        fragments += 1
                    block = block.next()
                self.assertTrue(images)
                self.assertLessEqual(max(images), dialog.browser.viewport().width())
                self.assertEqual(dialog.browser.horizontalScrollBar().maximum(), 0)
                widths.append(max(images))
            self.assertGreater(widths[1], widths[0])
        finally:
            dialog.close()  # a shown dialog left open stays the active window for later GUI tests
            dialog.deleteLater()

    def test_toolbar_topic_names_every_session_action(self):
        body = dict((key, body) for key, _, body in HELP_PAGES)["toolbar"]
        # The topic names the connect action by its current label and describes the Help icon.
        names = {"Connect": RunBar.CONNECTION_STATES["disconnected"][0], "Help": "Help icon"}
        labels = [names.get(name, name) for name in ACTIONS]
        for label in labels:
            with self.subTest(action=label):
                self.assertIn(f"<b>{label}</b>", body)


if __name__ == '__main__':
    unittest.main()
