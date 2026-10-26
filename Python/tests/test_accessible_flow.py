"""Guided navigation, settings recovery and reported timing contracts."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox, QStackedWidget
from build_manager.ui import ManagerPanel
from build_manager.run_ui import RunView
from build_manager.application_settings_ui import ApplicationSettingsDialog, apply_preferences
from build_manager.settings_ui import SettingsDialog
from build_manager.registry import Registry
from build_manager.bridge import ProjectBridge
from test_ui import OtherProject
import test_ui as ui_fixtures
import test_registry as registry_fixtures
import test_settings_async_ui as settings_fixtures


class AccessibleFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_navigation_requires_review_and_keeps_history_separate(self):
        with TemporaryDirectory() as directory:
            panel = ManagerPanel(OtherProject(Path(directory)))
            try:
                self.assertIsInstance(panel.stages, QStackedWidget)
                self.assertFalse(panel.view_run.isEnabled())
                self.assertFalse(panel.start.isEnabled())
                ui_fixtures.ManagerUITests.inspect(self, panel)
                self.assertEqual(panel.stages.currentIndex(), 1)
                self.assertIn('No delivery', panel.review_summary.text())
                panel.back.click()
                self.assertEqual(panel.stages.currentIndex(), 0)
                panel.past_runs.click()
                self.assertEqual(panel.stages.currentIndex(), 3)
                panel.new_run.click()
                self.assertEqual(panel.stages.currentIndex(), 0)
            finally:
                panel.close()

    def test_timing_uses_case_durations_and_resets_between_runs(self):
        with TemporaryDirectory() as directory:
            plan = OtherProject(Path(directory)).make_plan('example', 'Test', 'Local fixture')
            view = RunView()
            view.reset(plan)
            cases = [dict(name=name, seconds=seconds, status=status, suite='suite', classname='class', message='')
                for name, seconds, status in [('slow', 4., 'failed'), ('fast', 1., 'passed'), ('unknown', None, 'skipped')]]
            view.update_phase(dict(id=plan.phases[0].id, status='failed', seconds=3, tests=cases))
            view.complete(dict(status='failed', seconds=3))
            self.assertIn('3 reported tests', view.result_counts.text())
            self.assertIn('Average: 2.50s', view.timing_summary.text())
            self.assertIn('1 without duration', view.timing_summary.text())
            self.assertEqual(view.timings.topLevelItem(0).text(0), 'slow')
            self.assertIn('Problems', view.next_action.text())
            view.reset(plan)
            self.assertEqual(view.timings.topLevelItemCount(), 0)
            self.assertIn('0 reported tests', view.result_counts.text())
            view.close()

    def test_app_preferences_save_only_to_manager_profile_and_apply(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as directory:
            project = SimpleNamespace(registry=SimpleNamespace(directory=Path(directory)))
            original = QFont(self.app.font())
            try:
                dialog = ApplicationSettingsDialog(project)
                dialog.size.setValue(15)
                dialog.save()
                self.assertEqual(self.app.font().pointSize(), 15)
                self.assertEqual(json.loads(dialog.path.read_text())['values'], {'text_size': 15})
                dialog.close()
            finally:
                self.app.setFont(original)

    def test_registered_settings_load_without_approval_popup(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), TemporaryDirectory() as directory:
                fixture = registry_fixtures.RegistryTests()
                fixture.root = Path(directory)
                fixture.registry = Registry(fixture.root / 'private')
                root = fixture.fixture('project')
                (root / 'bridge.py').write_text('import json; print(json.dumps(dict(schema=1,result={"sample": {"value": "loaded"}})))')
                key = fixture.registry.add(root)
                if legacy:
                    fixture.registry.mutate(lambda data: data['projects'][key].update(trusted=False))
                project = ProjectBridge(fixture.registry, key)
                with patch.object(QMessageBox, 'question', side_effect=AssertionError('Unexpected approval popup')):
                    dialog = SettingsDialog(project)
                    try:
                        settings_fixtures.SettingsAsyncTests.wait(self, dialog)
                        self.assertEqual(dialog.controls['sample'].text(), 'loaded')
                    finally:
                        dialog.reject()

    def test_add_project_has_no_trust_menu_or_approval_popup(self):
        from build_manager.app import ManagerWindow
        with TemporaryDirectory() as directory:
            fixture = registry_fixtures.RegistryTests()
            fixture.root = Path(directory)
            fixture.registry = Registry(fixture.root / 'private')
            root = fixture.fixture('project')
            window = ManagerWindow(fixture.registry)
            try:
                with patch('build_manager.project_setup_ui.AddProjectDialog') as chooser, \
                        patch.object(QMessageBox, 'question', side_effect=AssertionError('Unexpected approval popup')):
                    chooser.return_value.exec.return_value = 1
                    chooser.return_value.root = root
                    window.add()
                    self.assertIsNotNone(window.panel)
                    self.assertTrue(fixture.registry.resolve(trusted=True)[0]['trusted'])
                actions = [action.text() for button in window.buttons if hasattr(button, 'menu') and button.menu() is not None
                           for action in button.menu().actions()]
                self.assertFalse(any('trust' in action.lower() for action in actions))
            finally:
                window.close()
