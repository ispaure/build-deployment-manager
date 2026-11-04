"""Real tooling worker dispatch with Qt mocked, never an installer invocation."""
import importlib.util
from pathlib import Path
from queue import Queue
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_project_tooling import status


class ToolingTransportTests(unittest.TestCase):
    def test_optional_update_action_maps_direct_adapter_method(self):
        from build_manager.adapter_sdk import supports
        self.assertTrue(supports(self.project(), 'tooling_update'))
        self.assertFalse(supports(SimpleNamespace(), 'tooling_update'))

    def worker(self, project, action):
        core = ModuleType('PySide6.QtCore')
        widgets = ModuleType('PySide6.QtWidgets')
        for name in ('QRunnable', 'QThreadPool', 'QTimer', 'Qt'): setattr(core, name, object)
        for name in ('QDialog', 'QHBoxLayout', 'QLabel', 'QMessageBox', 'QPushButton',
                     'QTreeWidget', 'QTreeWidgetItem', 'QVBoxLayout'): setattr(widgets, name, object)
        source = Path(__file__).resolve().parents[1] / 'build_manager/tooling_ui.py'
        spec = importlib.util.spec_from_file_location('build_manager._mock_tooling_ui', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'PySide6': ModuleType('PySide6'), 'PySide6.QtCore': core,
                                     'PySide6.QtWidgets': widgets}):
            spec.loader.exec_module(module)
        return module.ToolingTask(project, action, Queue())

    def project(self):
        return SimpleNamespace(tooling_status=Mock(return_value=status()),
                               update_tooling=Mock(return_value=status(True)))

    def test_status_does_not_update_or_load_settings(self):
        project = self.project(); task = self.worker(project, 'status'); task.run()
        value, error = task.results.get_nowait()
        self.assertFalse(value['ready']); self.assertIsNone(error)
        self.assertTrue(task.done.is_set()); project.update_tooling.assert_not_called()
        self.assertTrue(callable(project.tooling_status.call_args.kwargs['cancelled']))

    def test_update_forwards_explicit_confirmation_only_to_project_policy(self):
        project = self.project(); task = self.worker(project, 'update'); task.run()
        value, error = task.results.get_nowait()
        self.assertTrue(value['ready']); self.assertIsNone(error)
        self.assertTrue(project.update_tooling.call_args.kwargs['confirmed'])
        project.tooling_status.assert_not_called()

    def test_closed_queued_check_never_invokes_project(self):
        project = self.project(); task = self.worker(project, 'status')
        task.cancelled.set(); task.run()
        value, error = task.results.get_nowait()
        self.assertIsNone(value); self.assertIn('cancelled', error)
        project.tooling_status.assert_not_called(); project.update_tooling.assert_not_called()

    def test_invalid_bootstrap_result_is_an_error_without_fallback(self):
        project = self.project(); project.tooling_status.return_value = {'ready': True}
        task = self.worker(project, 'status'); task.run()
        value, error = task.results.get_nowait()
        self.assertIsNone(value); self.assertIn('readiness', error)
        self.assertTrue(task.done.is_set()); project.update_tooling.assert_not_called()
