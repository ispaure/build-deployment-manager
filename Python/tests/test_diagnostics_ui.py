"""Offscreen preview and clipboard tests using an isolated write callback."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QProcess, QThreadPool, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTreeWidgetItem
from shiboken6 import isValid

from build_manager import Phase, Plan
from build_manager.diagnostics import format_diagnostics
from build_manager.diagnostics_ui import DiagnosticPreview
from build_manager.ui import ManagerPanel


class DiagnosticPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialogs = []
        self.panels = []
        self.gates = []
        self.clipboard = Mock()

    def tearDown(self):
        for release in self.gates:
            release.set()
        for dialog in self.dialogs:
            if isValid(dialog):
                dialog.close()
        self.assertTrue(QThreadPool.globalInstance().waitForDone(5000))
        for panel in self.panels:
            panel.close()
            panel.deleteLater()
        self.drain()
        self.assertTrue(all(not isValid(dialog) for dialog in self.dialogs))

    def drain(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, predicate):
        deadline = monotonic() + 5
        while not predicate():
            self.assertLess(monotonic(), deadline, 'Diagnostic preview did not reach the expected state')
            QTest.qWait(10)

    def preview(self, factory=None):
        if factory is None:
            factory = lambda excerpt: 'Read-only fixture report' + ('\nA visible excerpt' if excerpt else '')
        dialog = DiagnosticPreview(factory, clipboard=self.clipboard)
        self.dialogs.append(dialog)
        dialog.show()
        return dialog

    def manager_panel(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        project = SimpleNamespace(platforms=('fixture',), operations=('Test',), description='Diagnostic fixture',
            runner_directory=Path(__file__).resolve().parents[2], results_directory=root / 'runs',
            row={'name': 'Diagnostic fixture'}, backend_options=lambda *_: ('Local fixture',))
        panel = ManagerPanel(project)
        self.panels.append(panel)
        panel.show()
        return panel, root

    def manager_preview(self, action):
        def isolated_preview(factory, parent):
            dialog = DiagnosticPreview(factory, parent, clipboard=self.clipboard)
            self.dialogs.append(dialog)
            return dialog

        with patch('build_manager.diagnostics_ui.DiagnosticPreview', side_effect=isolated_preview):
            action()
        self.assertTrue(self.dialogs, 'Manager did not open a diagnostic preview')
        return self.dialogs[-1]

    def test_preview_load_and_close_leave_clipboard_untouched(self):
        dialog = self.preview()
        self.assertFalse(dialog.copy_button.isEnabled())
        self.clipboard.assert_not_called()
        self.wait(dialog.copy_button.isEnabled)
        self.assertTrue(dialog.preview.isReadOnly())
        self.assertIn('A visible excerpt', dialog.preview.toPlainText())
        self.clipboard.assert_not_called()

        buttons = dialog.findChild(QDialogButtonBox)
        QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Close), Qt.MouseButton.LeftButton)
        self.drain()
        self.assertFalse(isValid(dialog))
        self.clipboard.assert_not_called()

    def test_explicit_copy_writes_exact_visible_text_and_leaves_preview_open(self):
        dialog = self.preview(lambda include: 'Résumé fixture\r\nSecond visible line\n')
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()
        self.assertIn('Résumé fixture', approved)
        self.clipboard.assert_not_called()

        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)

        self.clipboard.assert_called_once_with(approved)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.preview.toPlainText(), approved)
        self.assertIn('Copied', dialog.feedback.text())

    def test_excerpt_toggle_uses_the_frozen_caller_snapshot(self):
        caller_context = {'origin': 'Planning failure', 'project': 'Original fixture', 'preset': 'Original preset',
                          'error': 'Original fixture failure', 'traceback': 'Original fixture excerpt'}
        snapshot = deepcopy(caller_context)
        entered, release = Event(), Event()
        self.gates.append(release)

        def factory(include):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test release gate did not open')
            return format_diagnostics(None, context=snapshot, include_excerpt=include)

        dialog = self.preview(factory)
        self.wait(entered.is_set)
        caller_context.update(project='Replacement fixture', preset='Replacement preset',
                              error='Replacement fixture failure', traceback='Replacement fixture excerpt')
        release.set()
        self.wait(dialog.copy_button.isEnabled)
        with_excerpt = dialog.preview.toPlainText()
        self.assertIn('Original fixture excerpt', with_excerpt)
        self.assertNotIn('Replacement', with_excerpt)

        QTest.keyClick(dialog.include_excerpt, Qt.Key.Key_Space)
        without_excerpt = dialog.preview.toPlainText()
        self.assertIn('Original fixture failure', without_excerpt)
        self.assertIn('Original preset', without_excerpt)
        self.assertNotIn('Original fixture excerpt', without_excerpt)
        self.assertNotIn('Replacement', without_excerpt)
        self.clipboard.assert_not_called()

        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        self.clipboard.assert_called_once_with(without_excerpt)
        QTest.keyClick(dialog.include_excerpt, Qt.Key.Key_Space)
        self.assertEqual(dialog.preview.toPlainText(), with_excerpt)
        self.assertNotIn('Copied', dialog.feedback.text())

    def test_close_during_slow_read_retires_widget_before_worker_finishes(self):
        entered, release, finished = Event(), Event(), Event()
        self.gates.append(release)

        def slow_factory(include):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test release gate did not open')
            if not include:
                finished.set()
            return 'Late disposable worker result'

        dialog = self.preview(slow_factory)
        self.wait(entered.is_set)
        self.assertFalse(dialog.copy_button.isEnabled())
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.drain()
        self.assertFalse(isValid(dialog))
        self.assertFalse(finished.is_set())

        release.set()
        self.wait(finished.is_set)
        self.assertTrue(QThreadPool.globalInstance().waitForDone(5000))
        self.drain()
        self.assertFalse(isValid(dialog))
        self.clipboard.assert_not_called()

    def test_failed_clipboard_write_keeps_selectable_text_and_explains_failure(self):
        self.clipboard.side_effect = RuntimeError('fixture-private-clipboard-error')
        dialog = self.preview()
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()

        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)

        self.clipboard.assert_called_once_with(approved)
        self.assertEqual(dialog.preview.toPlainText(), approved)
        self.assertTrue(dialog.isVisible())
        self.assertIn('Could not copy', dialog.feedback.text())
        self.assertNotIn('fixture-private-clipboard-error', dialog.feedback.text())

    def test_formatter_failure_has_a_generic_preview_and_no_implicit_clipboard_write(self):
        def failed_factory(include):
            raise OSError('fixture-private-formatter-error')

        dialog = self.preview(failed_factory)
        self.wait(lambda: 'unavailable' in dialog.preview.toPlainText())

        self.assertNotIn('fixture-private-formatter-error', dialog.preview.toPlainText())
        self.clipboard.assert_not_called()

    def test_planning_failure_keeps_its_original_preset_after_the_draft_changes(self):
        panel, _ = self.manager_panel()
        picker = panel.configuration.preset
        picker.setItemText(0, 'Original fixture preset')
        panel.project.make_plan = Mock(side_effect=ValueError('Fixture planning failed at /Users/fixture-private/source.py'))

        panel.request_plan_preparation()
        self.wait(lambda: not panel.preparing)
        self.assertIn('Fixture planning failed', panel.status.text())
        self.assertTrue(panel.copy_preparation_diagnostics.isVisible())
        self.assertIsNone(panel.plan)
        self.assertIsNone(panel.result)
        panel.project.make_plan.assert_called_once()

        dialog = self.manager_preview(panel.copy_preparation_diagnostics.click)
        picker.setItemText(0, 'Replacement fixture preset')
        panel.revision.setText('replacement-draft')
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()
        self.assertIn('no run started', approved.lower())
        self.assertIn('Original fixture preset', approved)
        self.assertIn('Fixture planning failed', approved)
        self.assertNotIn('Replacement fixture preset', approved)
        self.assertNotIn('fixture-private', approved)
        self.clipboard.assert_not_called()

        QTest.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
        self.clipboard.assert_called_once_with(approved)

    def test_stale_or_cancelled_preparation_failure_offers_no_diagnostics(self):
        panel, _ = self.manager_panel()
        for invalidate in ('change draft', 'cancel'):
            with self.subTest(invalidate=invalidate):
                entered, release = Event(), Event()
                self.gates.append(release)

                def fail_later(*args, **kwargs):
                    entered.set()
                    release.wait(5)
                    raise ValueError('Failure from a retired planning request')

                panel.project.make_plan = fail_later
                panel.request_plan_preparation()
                self.wait(entered.is_set)
                if invalidate == 'change draft':
                    panel.revision.setText('replacement-draft')
                else:
                    panel.cancel_preparation.click()
                release.set()
                self.wait(lambda: not panel.preparing)
                self.assertTrue(panel.copy_preparation_diagnostics.isHidden())
                self.assertIsNone(panel.preparation_diagnostic)
                self.assertIsNone(panel.plan)
        self.clipboard.assert_not_called()

    def test_controller_crash_preview_uses_stderr_even_with_task_selected(self):
        panel, root = self.manager_panel()
        plan = self.fixture_plan(root)
        run = root / 'runs' / 'controller-fixture'
        run.mkdir(parents=True)
        panel.result = run / 'result.json'
        panel.result.write_text(json.dumps(dict(schema=1, status='passed', phases=[], plan_identity=plan.identity)))
        retained_bytes = panel.result.read_bytes()
        (run / 'workload.log').write_text('Unrelated workload log line', encoding='utf-8')
        panel.active_diagnostic_context = {'origin': 'Current run', 'preset': 'Controller fixture preset'}
        panel.initialize_results_workspace(plan)
        panel.update_phase(dict(id='fixture', status='running', log='workload.log'))
        from build_manager.redaction import Redactor
        panel.redact = Redactor(['fixture-explicit-private-value'])
        chunks = [b'Controller stderr fixture detail\n-----BEGIN PRIVATE ',
                  b'KEY-----\nfixture-key-body\n-----END PRIVATE KEY-----\n',
                  b'fixture-explicit-private-value\n']
        with patch.object(panel.process, 'readAllStandardError', side_effect=chunks):
            for _ in chunks:
                panel.read_errors()

        panel.finished(0, QProcess.ExitStatus.CrashExit)
        panel.run_view.results_workspace.inspect_phase('fixture')
        self.assertEqual(panel.run_view.selected, 'fixture')
        self.assertEqual(panel.run_view.outcome, 'failed')
        dialog = self.manager_preview(panel.run_view.outcome_view.copy.click)
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()

        self.assertIn('operation process crashed', approved.lower())
        self.assertIn('Controller stderr fixture detail', approved)
        self.assertIn('incomplete', approved.lower())
        self.assertIn('unknown', approved.lower())
        self.assertNotIn('Step: fixture', approved)
        self.assertNotIn('Unrelated workload log line', approved)
        self.assertNotIn('fixture-key-body', approved)
        self.assertNotIn('fixture-explicit-private-value', approved)
        self.assertEqual(panel.result.read_bytes(), retained_bytes)
        self.clipboard.assert_not_called()

    def test_compact_planning_failure_keeps_source_feedback_and_copy_separate(self):
        from test_toolbar_goals_ui import ToolbarGoalTests
        fixture = ToolbarGoalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window, panel = fixture.window, fixture.panel
        window.resize(900, 700)
        window.show()
        panel.revision.setText('preserve-this-current-draft')
        message = ('Could not prepare the plan. Required fixture compiler is unavailable. '
                   'Configure the fixture compiler before preparing again.')
        panel.preparation_message(message, details='Traceback\n' + 'Fixture failure\n' * 30)
        panel.copy_preparation_diagnostics.show()
        for _ in range(10):
            self.app.processEvents()
        controls = (panel.configuration.splitter, panel.configuration.blocker_strip,
                    panel.plan_feedback, panel.preparation_error_section, panel.copy_preparation_diagnostics)
        bottom = 0
        for control in controls:
            if not control.isVisible():
                continue
            top = control.mapTo(panel.configuration, QPoint(0, 0)).y()
            self.assertGreaterEqual(top, bottom)
            bottom = top + control.height()
        self.assertLessEqual(bottom, panel.configuration.height())
        self.assertEqual(panel.revision.text(), 'preserve-this-current-draft')

    def test_controller_excerpt_discards_a_multibyte_boundary_line(self):
        panel, root = self.manager_panel()
        panel.initialize_results_workspace(self.fixture_plan(root))
        chunk = ('Complete controller line\n' + 'é' * 262144).encode('utf-8')
        with patch.object(panel.process, 'readAllStandardError', return_value=chunk):
            panel.read_errors()
        self.assertTrue(panel.session.diagnostic_stderr_truncated)
        self.assertLessEqual(len(panel.session.diagnostic_stderr.encode('utf-8')), 262144)
        captured = panel.session.diagnostic_stderr
        with patch.object(panel.process, 'readAllStandardError', return_value=b'\nLater output\n'):
            panel.read_errors()
        self.assertEqual(panel.session.diagnostic_stderr, captured)
        panel.run_view.unverified('Controller process ended before a report was recorded')
        dialog = self.manager_preview(panel.run_view.outcome_view.copy.click)
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()
        self.assertIn('Complete controller line', approved)
        self.assertIn('boundary line omitted', approved)
        self.assertNotIn('é', approved)

    def test_compact_failed_summary_keeps_copy_in_the_initial_viewport(self):
        from test_toolbar_goals_ui import ToolbarGoalTests
        fixture = ToolbarGoalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window, panel = fixture.window, fixture.panel
        window.resize(900, 700)
        window.show()
        plan = Plan('Diagnostic fixture', 'Verify fixture', {}, (
            Phase('check', (sys.executable, '-V'), str(fixture.root), label='Check fixture quantity',
                  artifacts=('fixture.xml',), artifact_types={'fixture.xml': 'junit'}),
            Phase('build', (sys.executable, '-V'), str(fixture.root), label='Build synthetic output',
                  dependencies=('check',), artifacts=('output.txt',))), str(fixture.root / 'workspace'))
        panel.initialize_results_workspace(plan, [dict(id='check', status='failed', tests=[dict(
            name='quantity', classname='Fixture', suite='Checks', status='failed',
            message='AssertionError: 2 != 3: Fixture inventory must contain three items', seconds=.1)]),
            dict(id='build', status='skipped')])
        panel.run_view.complete(dict(status='failed'))
        panel.stages.setCurrentIndex(2)
        for _ in range(10):
            self.app.processEvents()
        button = panel.run_view.outcome_view.copy
        viewport = panel.run_view.summary_page.viewport()
        bounds = button.rect().translated(button.mapTo(viewport, QPoint(0, 0)))
        self.assertTrue(button.isVisible())
        self.assertTrue(viewport.rect().contains(bounds), (viewport.rect(), bounds))

    def test_saved_diagnostics_use_recorded_engine_and_no_current_preset(self):
        panel, root = self.manager_panel()
        panel.configuration.preset.setItemText(0, 'Current unrelated preset')
        plan = self.fixture_plan(root)
        run = root / 'runs' / 'saved-fixture'
        run.mkdir(parents=True)
        plan.save(run / 'plan.json')
        report_path = run / 'result.json'
        report_path.write_text(json.dumps(dict(schema=1, status='failed', plan_identity=plan.identity,
            engine={'api': 1, 'manager': {'commit': 'a' * 40}, 'commonUtils': {'commit': 'b' * 40}},
            phases=[dict(id='fixture', status='failed', exit_code=3, error='Recorded historical fixture failure')])))
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, str(report_path))

        panel.open_history(item)
        self.wait(lambda: panel.retained_job is None)
        self.assertIn('Viewing retained run', panel.status.text())
        dialog = self.manager_preview(panel.run_view.outcome_view.copy.click)
        self.wait(dialog.copy_button.isEnabled)
        approved = dialog.preview.toPlainText()

        for label in ('Saved run', 'saved-fixture', 'Recorded historical fixture failure', 'Not recorded',
                      'manager revision: ' + 'a' * 40, 'commonUtils revision: ' + 'b' * 40):
            self.assertIn(label, approved)
        self.assertNotIn('Current unrelated preset', approved)
        self.clipboard.assert_not_called()

    @staticmethod
    def fixture_plan(root):
        return Plan('Diagnostic fixture', 'Verify fixture', {}, (
            Phase('fixture', (sys.executable, '-V'), str(root), label='Fixture workload'),
        ), str(root / 'workspace'))

    def test_next_launch_offer_uses_real_window_and_dismisses_only_selected_report(self):
        from build_manager.app import ManagerWindow
        from build_manager.registry import Registry
        from build_manager.manager_diagnostics import DiagnosticStore
        from build_manager.diagnostics_ui import offer_manager_diagnostics
        from PySide6.QtWidgets import QPushButton, QComboBox
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = DiagnosticStore(root)
            session = store.start()
            session.record_exception(RuntimeError, RuntimeError('Synthetic manager error'), None)
            session.close()
            window = ManagerWindow(Registry(root))
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            try:
                offer_manager_diagnostics(window, store, store.pending())
                window.show()
                self.app.processEvents()
                picker = next(c for c in window.findChildren(QComboBox)
                              if c.accessibleName() == 'Previous manager diagnostic')
                self.assertEqual(picker.count(), 1)
                button = next(b for b in window.findChildren(QPushButton) if b.text() == 'Dismiss diagnostic')
                self.assertTrue(button.isVisible())
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                self.assertEqual(store.pending(), [])
            finally:
                window.close()
                window.deleteLater()
                self.drain()
