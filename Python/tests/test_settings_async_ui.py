"""Settings must show before loading, remain responsive and preserve failed edits."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from threading import Event
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from build_manager.settings_ui import SettingsDialog
from build_manager.ui import ManagerPanel
from test_ui import OtherProject
from test_journeys import CAPABILITY, integrated
from tempfile import TemporaryDirectory


class SettingsAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, dialog):
        deadline = time.monotonic() + 5
        while dialog.busy:
            self.app.processEvents(); time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)

    def test_dialog_visible_during_slow_load_and_close_discards_late_reply(self):
        entered, release = Event(), Event()
        class Project:
            def settings_view(self):
                entered.set(); release.wait(5)
                return {'group': {'value': 'fixture'}}
        dialog = SettingsDialog(Project())
        dialog.show(); self.app.processEvents()
        self.assertTrue(dialog.isVisible()); self.assertTrue(entered.wait(2))
        ticks = []; QTimer.singleShot(0, lambda: ticks.append(True)); self.app.processEvents()
        self.assertEqual(ticks, [True]); self.assertIn('Loading', dialog.status.text())
        dialog.reject(); release.set()
        self.app.processEvents()
        self.assertTrue(dialog.closed); self.assertEqual(dialog.controls, {})

    def test_failure_retry_empty_and_malformed_responses_have_visible_states(self):
        class Project:
            def settings_view(self): raise RuntimeError('synthetic adapter failure')
        project = Project(); dialog = SettingsDialog(project); self.wait(dialog)
        self.assertIn('Could not load', dialog.status.text()); self.assertFalse(dialog.retry.isHidden())
        project.settings_view = lambda: []
        dialog.load(); self.wait(dialog); self.assertIn('invalid settings', dialog.status.text())
        project.settings_view = lambda: {}
        dialog.load(); self.wait(dialog); self.assertIn('no editable settings', dialog.status.text()); dialog.reject()

    def test_save_failure_preserves_input_and_unsaved_close_requires_explicit_discard(self):
        class Project:
            def settings_view(self): return {'group': {'value': 'original'}}
            def save_settings(self, values): raise ValueError('synthetic save failure')
        dialog = SettingsDialog(Project()); self.wait(dialog)
        dialog.controls['group'].setText('changed'); dialog.save(); self.wait(dialog)
        self.assertIn('not saved', dialog.status.text()); self.assertEqual(dialog.controls['group'].text(), 'changed')
        self.assertTrue(dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            dialog.reject(); self.assertFalse(dialog.closed)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.reject(); self.assertTrue(dialog.closed)

    def test_goal_selection_conflict_and_modified_preset_are_clear(self):
        with TemporaryDirectory() as folder:
            project = OtherProject(Path(folder)); project.platforms = ('android', 'ios')
            project.journey_capability = CAPABILITY
            project.make_journey = lambda *a, **kw: integrated(Path(folder))
            panel = ManagerPanel(project)
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['ios'].setChecked(True)
            panel.destination_checks['firebase'].setChecked(True)
            panel.inspect_plan(); self.assertFalse(panel.preparing); self.assertIn('requires: android', panel.status.text())
            panel.platform_checks['android'].setChecked(True)
            panel.destination_checks['testflight'].setChecked(True)
            panel.inspect_plan()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
            self.assertIsNotNone(panel.plan); self.assertEqual(panel.start.text(), 'Start reviewed workflow')
            self.assertIn('firebase:fixture', panel.overview.toPlainText())
            panel.platform_checks['android'].setChecked(False)
            self.assertIsNone(panel.plan); self.assertTrue(panel.destination_checks['firebase'].isChecked())
            panel.close()
            project.workflow_presets = {'Firebase workflow': dict(platform='android', operation='Test', backend='Local fixture')}
            panel = ManagerPanel(project); panel.preset.setCurrentText('Firebase workflow')
            panel.platform.setCurrentText('ios')
            self.assertEqual(panel.preset.currentText(), 'Firebase workflow')
            self.assertIn('Modified', panel.preset_note.text()); panel.close()

    def test_real_gui_integrated_start_authorizes_selected_destinations(self):
        import json
        with TemporaryDirectory() as folder:
            root = Path(folder)
            project = OtherProject(root)
            project.platforms = ('android', 'ios'); project.journey_capability = CAPABILITY
            project.make_journey = lambda *a, **kw: integrated(root)
            panel = ManagerPanel(project)
            self.addCleanup(panel.close)
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            for control in (*panel.platform_checks.values(), *panel.destination_checks.values()):
                control.setChecked(True)
            panel.inspect_plan()
            deadline = time.monotonic() + 10
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
            panel.run_plan()
            def finish():
                while panel.cancel.isEnabled():
                    self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
                return json.loads(panel.result.read_text())
            last = finish(); self.assertEqual(last['status'], 'passed')
            self.assertFalse(panel.continue_run.isEnabled())
            self.assertIn('firebase:fixture/app/testers: passed', panel.run_view.destinations.text())
            panel.close()
            self.assertTrue(QThreadPool.globalInstance().waitForDone(5000))

    def test_group_approval_requires_selection_and_keeps_cancel_default(self):
        from build_manager.ui import EffectReviewDialog
        from PySide6.QtWidgets import QPushButton
        dialog = EffectReviewDialog('Fixture evidence', steps=('firebase', 'testflight'))
        buttons = dialog.findChild(QDialogButtonBox)
        approve = next(button for button in buttons.buttons() if 'Approve' in button.text())
        self.assertFalse(approve.isEnabled())
        self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
        dialog.approvals['firebase'].setChecked(True)
        self.assertTrue(approve.isEnabled()); self.assertFalse(dialog.approvals['testflight'].isChecked())
        dialog.reject()

    def test_legacy_platform_change_preserves_unavailable_host_until_explicit_choice(self):
        with TemporaryDirectory() as folder:
            project = OtherProject(Path(folder)); project.platforms = ('android', 'ios')
            project.backend_options = lambda target, *_: ('Android host',) if target == 'android' else ('iOS host',)
            panel = ManagerPanel(project); self.addCleanup(panel.close)
            self.assertEqual(panel.backend.currentText(), 'Android host')
            panel.platform.setCurrentText('ios')
            self.assertEqual(panel.backend.currentText(), 'Android host')
            panel.inspect_plan(); self.assertFalse(panel.preparing)
            self.assertIn('choices are retained', panel.status.text())
            panel.backend.setCurrentText('iOS host')
            panel.inspect_plan()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
            self.assertIsNotNone(panel.plan)
