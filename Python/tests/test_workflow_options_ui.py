"""Workflow-wide choices are visible for validation and isolated between presets."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import unittest
from PySide6.QtWidgets import QApplication, QFormLayout, QWidget

from build_manager.run_fields import validate_fields, validate_overrides
from build_manager.run_fields_ui import RunFieldsView


class WorkflowOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preset_choice_restores_and_absent_legacy_value_resets_to_default(self):
        row = dict(id='testing.reuse_verified_results', label='Reuse verified test results',
                   kind='choice', default='on', options={'on': 'On', 'off': 'Off (debug)'}, workflow_option=True)
        validate_fields([row], {'operations': []})
        view = RunFieldsView(SimpleNamespace(run_fields=[row]))
        self.addCleanup(view.close)
        for goal in ('validate', 'deliver', 'advanced'):
            view.update_context(goal, [], 'Test')
            view.restore({row['id']: 'off'})
            self.assertEqual(view.values(), {row['id']: 'off'})
            self.assertEqual(view.saved_values(), {row['id']: 'off'})
            view.restore({})
            self.assertEqual(view.values(), {row['id']: 'on'})
        with self.assertRaises(ValueError):
            validate_overrides([row], {row['id']: 'sometimes'})

    def test_workflow_controls_move_to_validation_form_and_back_for_advanced(self):
        row = dict(id='reuse', label='Reuse verified test results', kind='choice', default='on',
                   options={'on': 'On', 'off': 'Off'}, workflow_option=True)
        view = RunFieldsView(SimpleNamespace(run_fields=[row]))
        page = QWidget()
        form = QFormLayout(page)
        self.addCleanup(page.close)
        self.addCleanup(view.close)
        view.set_workflow_form(form)
        page.show()
        view.update_context('validate', [], '')
        self.app.processEvents()
        self.assertIs(view.controls['reuse'].parentWidget(), page)
        self.assertTrue(view.controls['reuse'].isVisible())
        view.update_context('advanced', [], 'Test')
        self.assertIs(view.controls['reuse'].parentWidget(), view)
