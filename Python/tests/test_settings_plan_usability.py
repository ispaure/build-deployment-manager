"""Visible recovery at the action that was blocked, without project approval prompts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
import unittest

from PySide6.QtWidgets import QApplication
from build_manager.ui import ManagerPanel
from build_manager.settings_ui import SettingsDialog
from test_ui import OtherProject
from test_journeys import CAPABILITY


class SettingsPlanUsabilityTests(unittest.TestCase):
    def test_conditional_host_fields_follow_unsaved_mode_and_preserve_values(self):
        project = SimpleNamespace(settings_view=lambda: {
            'mode': dict(value='guest', section='VM', choices=['guest', 'container']),
            'host': dict(value='saved host', section='VM', visible_when={'mode': 'container'})})
        dialog = SettingsDialog(project)
        self.addCleanup(lambda: (setattr(dialog, 'dirty', False), dialog.reject()))
        self.wait(lambda: dialog.busy)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(dialog.controls['host'].isVisible())
        dialog.controls['mode'].setCurrentText('container')
        self.app.processEvents()
        self.assertTrue(dialog.controls['host'].isVisible())
        self.assertEqual(dialog.controls['host'].text(), 'saved host')
        self.assertTrue(dialog.dirty)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, pending):
        deadline = time.monotonic() + 5
        while pending():
            self.app.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)
        self.app.processEvents()

    def test_settings_failure_shows_retry_without_approval(self):
        project = SimpleNamespace(settings_view=Mock(side_effect=ValueError('Interpreter missing')))
        dialog = SettingsDialog(project)
        self.addCleanup(dialog.reject)
        dialog.show()
        self.wait(lambda: dialog.busy)
        self.assertIn('Interpreter missing', dialog.status.text())
        self.assertFalse(dialog.retry.isHidden())
        self.assertTrue(dialog.help_text.isHidden())
        self.assertTrue(dialog.navigation.isHidden())

    def test_review_plan_checks_registration_errors_without_trust_prompt(self):
        with TemporaryDirectory() as directory:
            project = OtherProject(Path(directory))
            project.registry = SimpleNamespace(resolve=Mock(side_effect=ValueError('Project identity changed')))
            project.key = 'fixture'
            project.make_plan = Mock()
            panel = ManagerPanel(project)
            self.addCleanup(panel.close)
            panel.prepare.click()
            project.make_plan.assert_not_called()
            self.assertIn('Project identity changed', panel.plan_feedback.text())
            self.assertFalse(panel.start.isEnabled())

    def test_missing_platform_feedback_is_next_to_review_action(self):
        with TemporaryDirectory() as directory:
            project = OtherProject(Path(directory))
            project.journey_capability = CAPABILITY
            panel = ManagerPanel(project)
            self.addCleanup(panel.close)
            panel.show()
            panel.prepare.click()
            self.assertFalse(panel.preparing)
            self.assertEqual(panel.plan_feedback.text(), panel.status.text())
            self.assertIn('platform', panel.plan_feedback.text().lower())
            self.assertFalse(panel.start.isEnabled())

    def test_adapter_failure_stays_visible_at_review_action(self):
        with TemporaryDirectory() as directory:
            project = OtherProject(Path(directory))
            project.make_plan = Mock(side_effect=ValueError('Selected runtime is missing'))
            panel = ManagerPanel(project)
            self.addCleanup(panel.close)
            panel.show()
            panel.prepare.click()
            self.wait(lambda: panel.preparing)
            self.assertIn('Could not prepare the plan', panel.plan_feedback.text())
            self.assertIn('Selected runtime is missing', panel.plan_feedback.text())
            self.assertFalse(panel.start.isEnabled())
