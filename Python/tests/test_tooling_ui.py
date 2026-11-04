"""Project tooling is visible and repair stays explicit, isolated and asynchronous."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from build_manager.tooling_ui import ProjectToolingDialog
from test_project_tooling import status


class ToolingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.project = SimpleNamespace(tooling_status=Mock(return_value=status()),
                                       update_tooling=Mock(return_value=status(True)))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs: dialog.close()
        self.assertTrue(QThreadPool.globalInstance().waitForDone(2000))
        self.app.processEvents()

    def dialog(self):
        dialog = ProjectToolingDialog(self.project); self.dialogs.append(dialog)
        self.wait(dialog)
        return dialog

    def wait(self, dialog):
        deadline = time.monotonic() + 2
        while dialog.worker is not None:
            self.app.processEvents(); time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)

    def test_readonly_check_shows_both_environments_without_loading_settings(self):
        dialog = self.dialog()
        self.assertEqual(dialog.environments.topLevelItemCount(), 2)
        self.assertTrue(dialog.update.isEnabled())
        self.assertFalse(dialog.was_updated)
        self.project.update_tooling.assert_not_called()

    def test_update_requires_confirmation_then_refreshes_actual_readiness(self):
        dialog = self.dialog()
        with patch('build_manager.tooling_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            dialog.confirm_update()
        self.project.update_tooling.assert_not_called()
        with patch('build_manager.tooling_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.confirm_update(); self.wait(dialog)
        self.assertTrue(dialog.was_updated)
        self.assertTrue(dialog.last_status['ready'])
        self.assertTrue(self.project.update_tooling.call_args.kwargs['confirmed'])

    def test_blocked_active_environment_disables_update(self):
        self.project.tooling_status.return_value = status(blocked=True)
        dialog = self.dialog()
        self.assertFalse(dialog.update.isEnabled())
        dialog.confirm_update()
        self.project.update_tooling.assert_not_called()

    def test_update_cannot_be_abandoned_mid_install_by_closing_dialog(self):
        dialog = self.dialog(); release = Event(); entered = Event()
        def update(**_):
            entered.set(); release.wait(2); return status(True)
        self.project.update_tooling.side_effect = update
        try:
            with patch('build_manager.tooling_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                dialog.confirm_update()
            self.assertTrue(entered.wait(1))
            event = QCloseEvent(); dialog.closeEvent(event)
            self.assertFalse(event.isAccepted())
        finally:
            release.set()
            self.wait(dialog)

    def test_failed_recheck_clears_stale_ready_environment_rows(self):
        self.project.tooling_status.return_value = status(True)
        dialog = self.dialog()
        self.project.tooling_status.side_effect = ValueError('Bootstrap unavailable')
        dialog.start('status'); self.wait(dialog)
        self.assertEqual(dialog.environments.topLevelItemCount(), 0)
        self.assertFalse(dialog.update.isEnabled())
        self.assertIn('Bootstrap unavailable', dialog.message.text())

    def test_application_entrypoint_refreshes_idle_project_after_confirmed_repair(self):
        from build_manager.app import ManagerWindow
        view = SimpleNamespace(project=self.project, window=lambda: None)
        window = SimpleNamespace(refresh=Mock())
        with patch('build_manager.tooling_ui.ProjectToolingDialog') as factory:
            factory.return_value.was_updated = True
            ManagerWindow.open_project_tooling(window, view)
        factory.assert_called_once_with(self.project, None)
        window.refresh.assert_called_once_with(view=view, force=True)
