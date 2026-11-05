"""Guided navigation, settings recovery and reported timing contracts."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from fixture_directory import TemporaryDirectory
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
            slow = view.timings.topLevelItem(0)
            self.assertIsNone(view.timings.itemWidget(slow, 4))
            from PySide6.QtCore import Qt
            self.assertEqual(slow.data(4, Qt.ItemDataRole.UserRole), 1000)
            self.assertEqual(slow.data(4, Qt.ItemDataRole.AccessibleTextRole), 'slow: 4.00s')
            with patch.object(view.timings, 'clear', wraps=view.timings.clear) as clear:
                view.update_phase(dict(id=plan.phases[0].id, status='failed', live_tests=[dict(name='interim')]))
                clear.assert_not_called()
            cases[0]['message'] = 'new failure details'
            view.update_phase(dict(id=plan.phases[0].id, status='failed', tests=cases))
            self.assertEqual(view.tests.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole)['message'], 'new failure details')
            self.assertIn('View problems', view.next_action.text())
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
        from contextlib import ExitStack
        import sys
        import time
        import traceback
        from PySide6.QtCore import QThreadPool
        from build_manager import bridge_process
        from build_manager.settings_ui import SettingsTask
        from settings_load_contract import (BridgeRetirement, TaskCompletions, TimedEvent, budgets, cleanup_fixture,
                                             completed_call, finish_cleanup, wait_for_event)
        for legacy in (False, True):
            # An unverified worker must never race automatic fixture deletion.
            temporary = TemporaryDirectory(delete=False)
            with self.subTest(legacy=legacy), temporary as directory, ExitStack() as patches:
                finished, bridge_entered, bridge_retired = (TimedEvent() for _ in range(3))
                task_finished, tasks = None, TaskCompletions()
                dialog, primary, attempted, limits = None, None, False, None
                started = time.monotonic()
                try:
                    fixture = registry_fixtures.RegistryTests()
                    fixture.root = Path(directory)
                    fixture.registry = Registry(fixture.root / 'private')
                    root = fixture.fixture('project')
                    (root / 'bridge.py').write_text('import json; print(json.dumps(dict(schema=1,result={"sample": {"value": "loaded"}})))')
                    key = fixture.registry.add(root)
                    if legacy:
                        fixture.registry.mutate(lambda data: data['projects'][key].update(trusted=False))
                    project = ProjectBridge(fixture.registry, key)
                    limits = budgets(project.load_settings, stop_grace=bridge_process.STOP_GRACE,
                                    drain_timeout=bridge_process.DRAIN_TIMEOUT)
                    real_load, real_task, real_bridge = project.load_settings, SettingsTask.run, bridge_process.run
                    bridge = BridgeRetirement(project.root, [project.root / project.descriptor['interpreter'],
                                                             project.root / project.descriptor['bridge']])
                    bridge_entered, bridge_retired = bridge.entered, bridge.retired
                    def load(*args, real_load=real_load, finished=finished, **kwargs):
                        return completed_call(real_load, finished, *args, **kwargs)
                    def task_run(task, real_task=real_task, tasks=tasks):
                        return tasks.call(real_task, task)
                    def bridge_run(*args, real_bridge=real_bridge, bridge=bridge, **kwargs):
                        return bridge.call(real_bridge, *args, **kwargs)
                    patches.enter_context(patch.object(QMessageBox, 'question', side_effect=AssertionError('Unexpected approval popup')))
                    patches.enter_context(patch.object(project, 'load_settings', new=load))
                    patches.enter_context(patch.object(SettingsTask, 'run', new=task_run))
                    patches.enter_context(patch.object(bridge_process, 'run', new=bridge_run))
                    attempted = True
                    dialog = SettingsDialog(project)
                    task_finished = tasks.event(dialog.task)
                    wait_for_event(self, finished, limits['worker'], self.app.processEvents,
                                   stage='Real settings request and transport retirement')
                    # Keep the original five-second Queue/QTimer/render contract.
                    settings_fixtures.SettingsAsyncTests.wait(self, dialog)
                    self.assertEqual(dialog.controls['sample'].text(), 'loaded')
                except BaseException as error:
                    primary = error
                    try:
                        pool = QThreadPool.globalInstance()
                        stacks = [[dict(file=Path(frame.filename).name, function=frame.name, line=frame.lineno)
                                   for frame in traceback.extract_stack(current, limit=6)]
                                  for current in list(sys._current_frames().values())[:8]]
                        state = dict(legacy=legacy, seconds=time.monotonic()-started, limits=limits,
                            load_finished=finished.is_set(), task_finished=task_finished is not None and task_finished.is_set(),
                            bridge_entered=bridge_entered.is_set(), bridge_retired=bridge_retired.is_set(),
                            active_threads=pool.activeThreadCount(), stacks=stacks)
                        if dialog is not None:
                            state.update(busy=dialog.busy, queued_results=dialog.results.qsize(),
                                         timer_active=dialog.timer.isActive())
                        print('SETTINGS_LOAD_FAILURE=' + json.dumps(state), file=sys.stderr, flush=True)
                    except BaseException as diagnostic_error:
                        primary.add_note('Settings fixture diagnostic failed: ' + type(diagnostic_error).__name__)
                    raise
                finally:
                    def retire():
                        if attempted:
                            wait_for_event(self, task_finished if task_finished is not None else TimedEvent(),
                                           limits['retirement'], self.app.processEvents,
                                           stage='Cancelled settings worker retirement')
                            self.assertTrue(not bridge_entered.is_set() or bridge_retired.is_set(),
                                            'Settings bridge retirement is unverified; preserve fixture')
                    def remove():
                        if not cleanup_fixture(temporary, attempted=attempted,
                                task_finished=task_finished is not None and task_finished.is_set(), bridge_entered=bridge_entered.is_set(),
                                bridge_retired=bridge_retired.is_set()):
                            print('SETTINGS_FIXTURE_PRESERVED=' + json.dumps(dict(directory=directory,
                                task_finished=task_finished is not None and task_finished.is_set(), bridge_retired=bridge_retired.is_set())),
                                file=sys.stderr, flush=True)
                    finish_cleanup(primary, [lambda: dialog.reject() if dialog is not None else None,
                                             retire, remove])

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
                    chooser.return_value.registration_name.text.return_value = 'UI checkout'
                    window.add()
                    self.assertIsNotNone(window.panel)
                    self.assertEqual(fixture.registry.resolve()[0]['name'], 'UI checkout')
                    self.assertTrue(fixture.registry.resolve(trusted=True)[0]['trusted'])
                actions = [action.text() for button in window.buttons if hasattr(button, 'menu') and button.menu() is not None
                           for action in button.menu().actions()]
                self.assertFalse(any('trust' in action.lower() for action in actions))
            finally:
                window.close()
