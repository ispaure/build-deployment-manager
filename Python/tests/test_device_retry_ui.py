# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

"""GUI makes an uncertain device retry explicit and leaves the old run untouched."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton
from build_manager.ui import ManagerPanel
import test_device_retry as fixtures
from test_ui import OtherProject


class DeviceRetryUITests(unittest.TestCase):
    setUp = fixtures.DeviceRetryTests.setUp
    save = fixtures.DeviceRetryTests.save
    connection_failure = fixtures.DeviceRetryTests.connection_failure

    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def panel(self):
        project = OtherProject(self.root)
        project.descriptor = {'name': 'Fixture'}
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        panel.result = self.output / 'result.json'
        panel.initialize_results_workspace(self.plan, self.report['phases'])
        panel.run_view.complete(self.report)
        panel.update_run_actions()
        return panel

    def wait_prepared(self, panel):
        deadline = time.monotonic() + 5
        while panel.preparing:
            self.qt_app.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)

    def test_card_retry_click_authorizes_only_selected_device_without_dialogs(self):
        panel = self.panel()
        original = panel.result
        before = original.read_bytes()
        buttons = panel.run_view.results_workspace.flow.canvas.findChildren(QPushButton, 'cardAction')
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].property('actionKey'), 'install-ipad')
        with patch('build_manager.ui.QMessageBox.warning') as warning, \
                patch('build_manager.ui.QMessageBox.question') as question, \
                patch.object(panel.session, 'launch') as launch:
            buttons[0].click()
            self.wait_prepared(panel)
            launch.assert_called_once()
            self.assertTrue(launch.call_args.kwargs['confirmed'])
            warning.assert_not_called()
            question.assert_not_called()
        self.assertFalse(panel.plan.phases[-1].approval_required)
        self.assertEqual(panel.stages.currentIndex(), 2)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(self.receipt.exists())
        self.assertTrue(all(card.findChild(QPushButton, 'cardAction') is None or
            card.findChild(QPushButton, 'cardAction').isHidden() for card, _, _ in
            panel.run_view.results_workspace.flow.canvas.cards.values()))
        panel.set_busy(False)

    def test_android_retry_prompts_for_replacement_endpoint(self):
        self.connection_failure()
        panel = self.panel()
        with patch('build_manager.ui.QInputDialog.getText', return_value=('192.168.2.234:42821', True)) as prompt, \
                patch.object(panel.session, 'launch') as launch:
            panel.retry_device.click()
            self.wait_prepared(panel)
            prompt.assert_called_once()
            launch.assert_called_once()
        self.assertEqual(panel.plan.phases[-1].environment[fixtures.RETRY_CONNECTION], '192.168.2.234:42821')
        panel.set_busy(False)

    def test_changed_prepared_app_stops_before_launch(self):
        panel = self.panel()
        self.app.write_bytes(b'changed')
        with patch.object(panel.session, 'launch') as launch:
            panel.retry_device.click()
            self.wait_prepared(panel)
            launch.assert_not_called()
        self.assertFalse(self.receipt.exists())
