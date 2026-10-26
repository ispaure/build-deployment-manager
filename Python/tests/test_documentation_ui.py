"""The manager opens its own wiki through the pinned commonUtils reader."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWidgets import QApplication

from build_manager.app import ManagerWindow
from build_manager.registry import Registry


class DocumentationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_help_opens_manager_wiki_and_navigates_both_guides(self):
        with TemporaryDirectory() as folder:
            window = ManagerWindow(Registry(Path(folder)))
            try:
                window.show()
                window.set_active(True)
                self.assertTrue(window.help_button.isEnabled())
                self.assertIs(window.controls.itemAt(window.controls.count() - 1).widget(),
                              window.help_button)
                window.help_button.click()
                reader = window.documentation_window
                docs = Path(__file__).resolve().parents[2] / 'docs'
                self.assertEqual(reader.viewer.current_path, docs / 'docs.md')
                self.assertEqual(reader.viewer.wiki.catalog.root, docs)
                for target in ('user/user.md', 'development/development.md'):
                    reader.viewer.open_document(docs / 'docs.md')
                    reader.viewer.follow_link(QUrl(target))
                    self.assertEqual(reader.viewer.current_path, docs / target)
                    self.assertTrue(reader.viewer.browser.toPlainText())
                window.help_button.click()
                self.assertIs(window.documentation_window, reader)
                self.assertEqual(reader.viewer.current_path, docs / 'development/development.md')
                reader.close()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertIsNone(window.documentation_window)
                window.help_button.click()
                self.assertEqual(window.documentation_window.viewer.current_path, docs / 'docs.md')
            finally:
                if window.documentation_window is not None:
                    window.documentation_window.close()
                window.set_active(False)
                window.close()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
