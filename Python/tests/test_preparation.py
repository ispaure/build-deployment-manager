"""Workflow selections preserve GUI and saved-preset preparation semantics."""
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from build_manager.preparation import WorkflowSelection, preparation_request, validate_gui_selection
from build_manager.api import ManagerAPI


class PreparationTests(unittest.TestCase):
    def test_build_ignores_hidden_test_switches_and_captures_inputs(self):
        choices = dict(goal='build', operation='Test', platform='host', backend='Local',
                       revision='HEAD', pattern='hidden filter', suite='hidden suite', build_override=42,
                       run_options={'verbose': True}, run_overrides={'notes': 'reviewed'})
        selection = WorkflowSelection.from_choices(choices)
        choices['run_overrides']['notes'] = 'later edit'
        project = Mock()
        preparation_request(selection).prepare(project)
        project.make_plan.assert_called_once_with('Build', 'host', 'Local', revision='HEAD',
            pattern='', release_tag='', build_override='42', run_overrides={'notes': 'reviewed'})
        project.make_journey.assert_not_called()

    def test_journey_excludes_legacy_options_and_unselected_backends(self):
        selection = WorkflowSelection.from_choices(dict(goal='validate', selected_platforms=['host'],
            selected_destinations=['devices'], platform_backends={'host': 'Local', 'other': 'VM'},
            suite='hidden', run_options={'verbose': True}))
        project = Mock()
        preparation_request(selection, integrated=True).prepare(project)
        project.make_journey.assert_called_once_with('validate', ['host'], [], revision='working-tree',
            pattern='', release_tag='', build_override='', backends={'host': 'Local'})
        request = preparation_request(selection, integrated=True, include_backends=False)
        self.assertNotIn('backends', request.options)

    def test_invalid_combination_is_rejected_before_adapter_execution(self):
        project = SimpleNamespace(operations=['Test'], backend_options=lambda *_: ['Local'])
        with self.assertRaisesRegex(ValueError, 'do not work together'):
            validate_gui_selection(project, WorkflowSelection(operation='Test', backend='VM'), integrated=False)

    def test_preset_and_gui_share_options_and_keep_project_defaults(self):
        choices = dict(goal='advanced', operation='Test', platform='host', backend='Local',
                       suite='portable', run_options={'verbose': True})
        project = SimpleNamespace(row={'presets': {'Checks': choices}}, workflow_presets={},
                                  run_options={'verbose': {}}, make_plan=Mock())
        api = ManagerAPI.__new__(ManagerAPI)
        api.registry = Mock()
        with patch.object(api, '_project', return_value=project):
            api.prepare_preset('Checks')
        preset_call = project.make_plan.call_args
        project.make_plan.reset_mock()
        preparation_request(WorkflowSelection.from_choices(choices)).prepare(project)
        self.assertEqual(project.make_plan.call_args, preset_call)
        self.assertNotIn('run_overrides', choices)

    def test_preset_journey_fills_missing_selected_backend_only(self):
        choices = dict(goal='validate', selected_platforms=['host', 'other'],
                       platform_backends={'host': 'VM'})
        project = SimpleNamespace(row={'presets': {'Checks': choices}}, workflow_presets={},
            platforms=['host', 'other'], journey_capability={'platforms': {
                'host': {'backend': 'Local'}, 'other': {'backend': 'Local'}}}, make_journey=Mock())
        api = ManagerAPI.__new__(ManagerAPI)
        api.registry = Mock()
        with patch.object(api, '_project', return_value=project):
            api.prepare_preset('Checks')
        self.assertEqual(project.make_journey.call_args.kwargs['backends'], {'host': 'VM', 'other': 'Local'})
        self.assertEqual(choices['platform_backends'], {'host': 'VM'})

    def test_new_core_modules_import_without_qt_or_project_code(self):
        code = '''import sys
from build_manager import preparation, run_state, workflow_graph, workflow_presentation, scheduling, run_recording
assert not any(name.startswith(('PySide6', 'Python.', 'mobile.', 'features.')) for name in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
