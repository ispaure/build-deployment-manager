"""GUI makes an uncertain device retry explicit and leaves the old run untouched."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from build_manager.ui import ManagerPanel
import test_device_retry as fixtures
from test_ui import OtherProject


class DeviceRetryUITests(unittest.TestCase):
    setUp = fixtures.DeviceRetryTests.setUp
    save = fixtures.DeviceRetryTests.save

    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def panel(self):
        project = OtherProject(self.root)
        project.descriptor = {'name': 'Fixture'}
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        panel.result = self.output / 'result.json'
        panel.seed_run(self.plan, self.report['phases'])
        panel.run_view.complete(self.report)
        panel.update_run_actions()
        return panel

    def test_decline_does_not_prepare_or_install(self):
        panel = self.panel()
        self.assertFalse(panel.retry_device.isHidden())
        with patch('build_manager.ui.QMessageBox.warning', return_value=QMessageBox.StandardButton.No), \
                patch('build_manager.device_retry.prepare') as prepare:
            panel.retry_device.click()
        prepare.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_accept_prepares_review_without_launching_or_rewriting_unknown(self):
        panel = self.panel()
        before = panel.result.read_bytes()
        with patch('build_manager.ui.QMessageBox.warning', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(panel.session, 'launch') as launch:
            panel.retry_device.click()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.qt_app.processEvents()
                time.sleep(.005)
                self.assertLess(time.monotonic(), deadline)
            launch.assert_not_called()
        self.assertEqual(panel.plan.operation, 'Explicit device install retry')
        self.assertEqual(panel.stages.currentIndex(), 1)
        self.assertEqual(panel.result.read_bytes(), before)
        self.assertFalse(self.receipt.exists())
