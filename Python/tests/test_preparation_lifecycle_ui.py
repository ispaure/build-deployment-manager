"""Pending plan preparation cannot execute, replace newer choices, or outlive close."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from build_manager.ui import ManagerPanel
from build_manager.selection_persistence_ui import SelectionPersistence
from test_ui import OtherProject


class PreparationLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.release, self.entered = Event(), Event()
        self.project = OtherProject(self.root)
        self.panel = ManagerPanel(self.project)
        self.panel.show()
        self.app.processEvents()
        self.calls = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        self.panel.cancel_operation()
        self.pump(lambda: not self.panel.preparing)
        self.panel.close()
        self.pump(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
        self.app.processEvents()
        self.temporary.cleanup()

    def pump(self, condition, timeout=5):
        until = time.monotonic() + timeout
        while not condition():
            self.app.processEvents()
            time.sleep(.002)
            self.assertLess(time.monotonic(), until, 'Owned UI work did not retire')
        self.app.processEvents()

    def gated(self, *, failure=False):
        original = self.project.make_plan
        def prepare(*args, **kwargs):
            self.calls.append((args, kwargs))
            self.entered.set()
            if not self.release.wait(5):
                raise RuntimeError('Fixture not released')
            if failure:
                raise ValueError('late obsolete error')
            return original(*args, **kwargs)
        self.project.make_plan = prepare
        self.panel.request_plan_preparation()
        self.pump(self.entered.is_set)

    def test_history_navigation_and_repeated_click_keep_one_pending_request(self):
        self.gated()
        panel = self.panel
        panel.request_plan_preparation()
        panel.prepare.click()
        panel.past_runs.click()
        self.assertEqual(panel.stages.currentIndex(), 3)
        self.assertTrue(panel.current_run.isVisible())
        self.assertTrue(panel.cancel_preparation.isEnabled())
        self.assertFalse(panel.start.isEnabled())
        self.assertEqual(len(self.calls), 1)
        self.release.set()
        self.pump(lambda: not panel.preparing)
        self.assertEqual(panel.stages.currentIndex(), 3)
        panel.current_run.click()
        self.assertEqual(panel.stages.currentIndex(), 0)
        self.assertTrue(panel.stage_tabs.isTabEnabled(1))
        self.assertTrue(panel.start.isEnabled())

    def test_changed_selection_retires_late_success_and_late_error(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                original = self.project.make_plan
                self.release.clear(); self.entered.clear()
                self.gated(failure=failure)
                self.panel.revision.setText('new-choice-' + str(failure))
                self.assertTrue(self.panel.preparation_job.cancelled.is_set())
                self.release.set()
                self.pump(lambda: not self.panel.preparing)
                self.assertEqual(self.panel.preparation_state, 'superseded')
                self.assertIsNone(self.panel.plan)
                self.assertFalse(self.panel.start.isEnabled())
                self.assertNotIn('late obsolete error', self.panel.status.text())
                self.project.make_plan = original

    def test_cancel_and_close_do_not_present_a_late_plan(self):
        self.gated()
        with patch.object(self.panel, 'present_plan', wraps=self.panel.present_plan) as present:
            self.panel.cancel_preparation.click()
            self.assertEqual(self.panel.preparation_state, 'cancelling')
            self.assertTrue(self.panel.preparing)
            self.assertFalse(self.panel.prepare.isEnabled())
            self.panel.close()
            self.assertTrue(self.panel.closing)
            self.release.set()
            self.pump(lambda: not self.panel.preparing)
            present.assert_not_called()
            self.assertIsNone(self.panel.plan)
            self.assertFalse(self.panel.start.isEnabled())

    def test_registry_resolution_and_selection_write_do_not_block_gui(self):
        gui = get_ident()
        calls = []
        class Registry:
            def resolve(store, key):
                calls.append(('resolve', get_ident()))
                time.sleep(.25)
            def save_selections(store, key, choices):
                calls.append(('save', get_ident(), choices))
                time.sleep(.25)
        registry = Registry()
        self.project.registry, self.project.key = registry, 'fixture'
        store = SelectionPersistence(registry)
        store.submit('fixture', {'revision': 'old'})
        beats = []
        timer = QTimer(); timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(time.monotonic()))
        timer.start()
        started = time.monotonic()
        self.panel.request_plan_preparation()
        self.assertLess(time.monotonic()-started, .15)
        store.submit('fixture', {'revision': 'latest'})
        self.pump(lambda: not self.panel.preparing and not store.active and not store.pending)
        timer.stop()
        self.assertGreater(len(beats), 10)
        self.assertTrue(all(row[1] != gui for row in calls))
        self.assertEqual(calls[-1][2], {'revision': 'latest'})
        store.deleteLater()

    def test_failure_is_visible_and_new_request_can_succeed(self):
        original = self.project.make_plan
        self.gated(failure=True)
        self.release.set()
        self.pump(lambda: not self.panel.preparing)
        self.assertEqual(self.panel.preparation_state, 'failed')
        self.assertIn('late obsolete error', self.panel.status.text())
        self.assertTrue(self.panel.prepare.isEnabled())
        self.project.make_plan = original
        self.panel.request_plan_preparation()
        self.pump(lambda: not self.panel.preparing)
        self.assertEqual(self.panel.preparation_state, 'ready')
        self.assertTrue(self.panel.start.isEnabled())
        self.assertEqual(self.panel.process.state(), self.panel.process.ProcessState.NotRunning)

    def test_pending_selection_saves_coalesce_and_finish_before_explicit_write(self):
        saved, after = [], []
        class Registry:
            def save_selections(store, key, choices):
                if not saved:
                    self.entered.set()
                    if not self.release.wait(5):
                        raise RuntimeError('Fixture not released')
                saved.append((key, choices))
        store = SelectionPersistence(Registry())
        store.submit('fixture', {'revision': 'first'})
        self.pump(self.entered.is_set)
        store.submit('fixture', {'revision': 'intermediate'})
        store.submit('fixture', {'revision': 'latest'})
        store.after_flush(lambda: after.extend(saved))
        self.assertEqual(after, [])
        self.release.set()
        self.pump(lambda: bool(after))
        self.assertEqual(saved, [('fixture', {'revision': 'first'}), ('fixture', {'revision': 'latest'})])
        self.assertEqual(after, saved)
        store.deleteLater()

    def test_failed_save_is_retained_without_hidden_retry_and_same_value_can_retry(self):
        attempts, failures, settled, callbacks = [], [], [], []
        class Registry:
            def save_selections(store, key, choices):
                attempts.append((key, choices))
                if len(attempts) == 1:
                    raise OSError('Synthetic lock contention')
        store = SelectionPersistence(Registry())
        store.failed.connect(failures.append)
        store.settled.connect(lambda: settled.append(True))
        choices = {'revision': 'keep me'}
        store.submit('fixture', choices)
        store.after_flush(lambda: callbacks.append(True))
        self.pump(lambda: bool(failures))
        self.assertFalse(store.timer.isActive())
        self.assertFalse(store.flush())
        self.assertEqual(store.unsaved, {'fixture': choices})
        self.assertEqual(len(attempts), 1)
        self.assertEqual(settled, [])
        self.assertEqual(callbacks, [])
        self.assertIn('queued change was not saved', failures[0])
        store.submit('fixture', choices)
        self.pump(lambda: bool(settled))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(store.unsaved, {})
        self.assertEqual(callbacks, [])
        store.deleteLater()


class WindowPreparationLifecycleTests(unittest.TestCase):
    from test_toolbar_goals_ui import ToolbarGoalTests as Fixture
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    pump = PreparationLifecycleTests.pump

    def setUp(self):
        self.Fixture.setUp(self)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.window.show()
        self.release, self.entered = Event(), Event()
        self.addCleanup(self.release.set)
        self.app.processEvents()

    def block_writer(self, *, fail=False):
        original = self.window.registry.save_selections
        def save(key, choices):
            self.entered.set()
            if not self.release.wait(5):
                raise RuntimeError('Fixture not released')
            if fail:
                raise OSError('Synthetic save failure')
            original(key, choices)
        self.window.registry.save_selections = save
        self.panel.revision.setText('must persist before close')
        self.pump(self.entered.is_set)
        return original

    def test_close_waiting_for_writer_gates_new_work_and_rechecks_completion(self):
        self.block_writer()
        self.assertFalse(self.window.close())
        self.assertTrue(self.panel.close_requested)
        self.assertFalse(self.panel.prepare.isEnabled())
        with patch.object(self.panel.session, 'launch') as launch:
            from test_journeys import integrated
            self.panel.plan = integrated(self.root)
            self.panel.request_plan_preparation()
            self.panel.request_connection_check_plan()
            self.panel.run_plan()
            self.panel.resume_workflow(self.root / 'unused.json')
            self.assertFalse(self.panel.preparing)
            self.assertFalse(self.panel.reviewing)
            self.assertIsNone(self.window.new_run_tab(self.window.run_workspace))
            launch.assert_not_called()
        self.release.set()
        self.pump(lambda: not self.window.isVisible())
        self.assertEqual(self.data['projects']['one']['selections']['revision'], 'must persist before close')

    def test_failed_write_aborts_close_and_explicit_close_retry_succeeds(self):
        original = self.block_writer(fail=True)
        self.assertFalse(self.window.close())
        self.release.set()
        self.pump(lambda: bool(self.window.selection_store.unsaved))
        self.assertFalse(self.window.close_pending)
        self.assertFalse(self.panel.close_requested)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.isEnabled())
        self.assertIn('window remains open', self.panel.status.text())
        self.window.registry.save_selections = original
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Retry):
            self.window.close()
        self.pump(lambda: not self.window.isVisible())
        self.assertEqual(self.data['projects']['one']['selections']['revision'], 'must persist before close')

    def test_close_during_chunked_render_queues_recheck_after_synchronous_cancellation(self):
        from dataclasses import replace
        from build_manager import Phase
        from test_journeys import integrated
        plan = replace(integrated(self.root), phases=tuple(
            Phase('check.' + str(index), ('fixture',), str(self.root), effect='test') for index in range(500)),
            journey={})
        self.panel.begin_preparation(lambda *_: plan)
        self.pump(lambda: self.panel.preparation_state == 'rendering')
        self.assertTrue(self.panel.review_workspace.rendering)
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.window.close()
        self.assertFalse(self.panel.preparing)
        self.pump(lambda: not self.window.isVisible())
        self.assertIsNone(self.panel.plan)

    def test_failed_choices_remain_visible_when_close_first_waits_for_active_work(self):
        self.block_writer(fail=True)
        self.release.set()
        self.pump(lambda: bool(self.window.selection_store.unsaved))
        self.panel.set_busy(True)
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            self.window.close()
        self.assertTrue(self.window.close_pending)
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            self.panel.set_busy(False)
            self.pump(lambda: not self.window.close_pending)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.selection_store.unsaved)
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.Discard):
            self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertNotIn('selections', self.data['projects']['one'])

    def test_non_last_dock_closes_in_one_request_during_chunked_render(self):
        from dataclasses import replace
        from build_manager import Phase
        from test_journeys import integrated
        first = self.panel
        dock = self.window.run_workspace.docks[0]
        sibling = self.window.run_workspace.add_view(first.project_key)
        plan = replace(integrated(self.root), phases=tuple(
            Phase('check.' + str(index), ('fixture',), str(self.root), effect='test') for index in range(500)),
            journey={})
        first.begin_preparation(lambda *_: plan)
        self.pump(lambda: first.preparation_state == 'rendering')
        self.assertTrue(dock.close())
        self.pump(lambda: dock not in self.window.run_workspace.all_docks)
        self.assertTrue(self.window.isVisible())
        self.assertIs(self.window.panel, sibling)
        self.assertFalse(self.window.close_pending)

    def test_late_defaults_and_saved_evidence_cannot_overwrite_newer_user_choices(self):
        from build_manager.app import SavedRunRequest
        old = self.panel
        newer = self.window.run_workspace.add_view(old.project_key)
        saved = self.window.run_workspace.add_view(SavedRunRequest(old.project_key, old.project))
        newer.revision.setText('newest user choice')
        before = old.selection_revision
        old.configuration.run_fields.defaults_loaded.emit()
        self.window.project_settings_saved(newer)
        saved.selection_changed.emit({'revision': 'old evidence choices'})
        self.assertGreater(old.selection_revision, before)
        self.pump(lambda: self.window.selection_store.flush())
        self.assertEqual(self.data['projects']['one']['selections']['revision'], 'newest user choice')
        self.assertEqual(old.revision.text(), 'working-tree')
