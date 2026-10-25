"""Behavioral coverage for the guided UI using real fixture commands."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog, QPlainTextEdit
from build_manager.ui import EffectReviewDialog, ManagerPanel
import test_ui as fixtures


class GuidedUITests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ManagerUITests.setUpClass.__func__)
    setUp = fixtures.ManagerUITests.setUp
    inspect = fixtures.ManagerUITests.inspect
    finish = fixtures.ManagerUITests.finish

    def panel(self, project=None):
        panel = ManagerPanel(project or fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        return panel

    def wait_history(self, panel):
        deadline = time.monotonic() + 5
        while panel.history_loading or panel.history_refresh_pending:
            self.app.processEvents()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.005)

    def test_review_is_readable_and_all_steps_are_seeded_before_process_events(self):
        panel = self.panel()
        self.inspect(panel)
        self.assertEqual(panel.stages.currentIndex(), 1)
        self.assertIn('Steps in execution order', panel.overview.toPlainText())
        self.assertIn('example', panel.overview.toPlainText())
        panel.run_plan()
        self.assertEqual(panel.stages.currentIndex(), 2)
        self.assertEqual(panel.phase_status.topLevelItemCount(), 1)
        self.assertEqual(panel.phase_status.topLevelItem(0).text(1), 'queued')
        self.finish(panel)
        self.assertEqual(panel.phase_status.topLevelItem(0).text(1), 'passed')
        self.assertEqual(panel.run_view.progress.value(), 1)

    def test_inspecting_another_plan_does_not_relabel_existing_results(self):
        from dataclasses import replace
        project = fixtures.OtherProject(self.root)
        panel = self.panel(project)
        self.inspect(panel)
        panel.run_plan()
        self.finish(panel)
        original = project.make_plan
        project.make_plan = lambda *a, **k: replace(original(*a, **k), source={'revision': 'new-source'})
        self.inspect(panel)
        self.assertIn('new-source', panel.overview.toPlainText())
        self.assertNotIn('new-source', panel.run_view.context.text())
        self.assertIn('fixture', panel.run_view.context.text())

    def test_selected_suite_reaches_adapter_and_invalidates_review(self):
        project = fixtures.OtherProject(self.root)
        project.test_suites = [dict(id='portable.contracts', label='Contracts', tier='contracts',
                                   platforms=['example'], operations=['Test'])]
        received = []
        original = project.make_plan
        def make_plan(*args, **kwargs):
            received.append(kwargs)
            return original(*args, **kwargs)
        project.make_plan = make_plan
        panel = self.panel(project)
        panel.suite.setCurrentIndex(1)
        self.inspect(panel)
        self.assertEqual(received[0]['suite'], 'portable.contracts')
        panel.suite.setCurrentIndex(0)
        self.assertIsNone(panel.plan)
        self.assertFalse(panel.start.isEnabled())
        self.inspect(panel)
        self.assertNotIn('suite', received[1])

    def test_unavailable_preset_cannot_silently_fall_back_to_local_execution(self):
        project = fixtures.OtherProject(self.root)
        project.workflow_presets = {'Native release': dict(platform='example', operation='Test', backend='Unavailable host')}
        panel = self.panel(project)
        panel.preset.setCurrentText('Native release')
        panel.inspect_plan()
        self.assertFalse(panel.preparing)
        self.assertIsNone(panel.plan)
        self.assertIn('backend is unavailable', panel.status.text())
        panel.preset.setCurrentIndex(0)
        self.inspect(panel)
        self.assertTrue(panel.start.isEnabled())

    def test_real_failed_cases_are_filterable_and_retained_in_history(self):
        report_path = self.root / 'cases.xml'
        xml = ('<testsuite name="Contracts"><testcase classname="One" name="okay" time=".25"/>'
               '<testcase classname="One" name="broken" time="1.25"><failure message="expected green">trace</failure></testcase>'
               '<testcase classname="One" name="unavailable"><skipped message="native host"/></testcase></testsuite>')
        project = fixtures.OtherProject(self.root, code=f'from pathlib import Path; Path({str(report_path)!r}).write_text({xml!r}); raise SystemExit(1)')
        original = project.make_plan
        def make_plan(*args, **kwargs):
            from dataclasses import replace
            plan = original(*args, **kwargs)
            phase = replace(plan.phases[0], artifacts=(str(report_path),), artifact_types={str(report_path): 'junit'})
            return replace(plan, phases=(phase,))
        project.make_plan = make_plan
        panel = self.panel(project)
        self.inspect(panel)
        panel.run_plan()
        self.assertEqual(self.finish(panel)['status'], 'failed')
        view = panel.run_view
        self.assertEqual(view.tests.topLevelItemCount(), 3)
        self.assertIn('1 skipped', view.test_summary.text())
        view.filter.setCurrentText('Problems')
        self.assertTrue(view.tests.topLevelItem(0).isHidden())
        broken = view.tests.topLevelItem(1)
        self.assertFalse(broken.isHidden())
        self.assertEqual(broken.text(2), '1.25s')
        view.tests.setCurrentItem(broken)
        self.assertIn('expected green', view.test_detail.toPlainText())
        view.search.setText('no such case')
        self.assertTrue(broken.isHidden())
        self.wait_history(panel)
        self.assertEqual(panel.history.topLevelItemCount(), 1)
        panel.open_history(panel.history.topLevelItem(0))
        self.assertIsNone(panel.plan)
        self.assertFalse(panel.start.isEnabled())
        self.assertEqual(view.tests.topLevelItemCount(), 3)
        self.assertTrue(panel.continue_run.isEnabled())

    def test_running_steps_have_independent_clocks(self):
        panel = self.panel()
        self.inspect(panel)
        panel.seed_run(panel.plan)
        view = panel.run_view
        view.update_phase(dict(id='example', status='running'))
        view.update_phase(dict(id='other', status='running'))
        view.started['example'] = time.monotonic() - 5
        view.started['other'] = time.monotonic() - 2
        view.tick()
        self.assertTrue(view.rows['example'].text(2).startswith('5.'))
        self.assertTrue(view.rows['other'].text(2).startswith('2.'))
        view.update_phase(dict(id='example', status='passed', seconds=5.3))
        self.assertNotIn('example', view.started)
        self.assertIn('other', view.started)
        self.assertEqual(view.rows['example'].text(2), '5.30s')

    def test_plan_values_with_password_or_pem_do_not_break_redaction_or_ui(self):
        project = fixtures.OtherProject(self.root)
        original = project.make_plan
        def make_plan(*args, **kwargs):
            from dataclasses import replace
            return replace(original(*args, **kwargs), source={'revision': 'fixed', 'detail': 'password=privatevalue'},
                           settings={'key': '-----BEGIN PRIVATE KEY-----\nprivatebytes\n-----END PRIVATE KEY-----'})
        project.make_plan = make_plan
        panel = self.panel(project)
        self.inspect(panel)
        text = panel.plan_data.toPlainText() + panel.overview.toPlainText()
        self.assertNotIn('privatevalue', text)
        self.assertNotIn('privatebytes', text)
        self.assertTrue(panel.start.isEnabled())
        json.loads(panel.plan_data.toPlainText())

    def test_approval_dialog_shows_retained_evidence_and_cancel_is_default(self):
        dialog = EffectReviewDialog('source: fixed\nartifact: checked.zip\nSHA-256: exact')
        self.addCleanup(dialog.close)
        self.assertIn('checked.zip', dialog.findChild(QPlainTextEdit).toPlainText())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_delivery_review_includes_prepared_package_identity_and_redacts_evidence(self):
        panel = self.panel()
        self.inspect(panel)
        evidence = self.root / 'identity.json'
        evidence.write_text(json.dumps(dict(package='example.apk', version='1.2.3', destination='testers',
                                            detail='password=privatevalue')))
        report = dict(phases=[dict(id='example', status='passed', artifacts=[dict(path=str(evidence), sha256='verified')])])
        with patch('build_manager.ui.EffectReviewDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.assertFalse(panel.confirm_continuation(panel.plan, report, ['delivery']))
        text = dialog.call_args.args[0]
        self.assertIn('example.apk', text)
        self.assertIn('1.2.3', text)
        self.assertIn('testers', text)
        self.assertNotIn('privatevalue', text)

    def test_corrupt_history_is_actionable_without_enabling_execution(self):
        panel = self.panel()
        folder = panel.project.results_directory / 'broken'
        folder.mkdir(parents=True)
        (folder / 'result.json').write_text('[]')
        panel.refresh_history()
        self.wait_history(panel)
        self.assertEqual(panel.history.topLevelItem(0).text(2), 'unreadable')
        panel.open_history(panel.history.topLevelItem(0))
        self.assertIn('Cannot read', panel.status.text())
        self.assertFalse(panel.start.isEnabled())

    def test_unknown_effect_cannot_open_approval_or_launch_a_retry(self):
        panel = self.panel(fixtures.OtherProject(self.root, effect='upload'))
        self.inspect(panel)
        folder = self.root / 'unknown'
        folder.mkdir()
        plan = panel.plan
        plan.save(folder / 'plan.json')
        result = folder / 'result.json'
        result.write_text(json.dumps(dict(schema=1, plan_identity=plan.identity, status='unknown',
                         phases=[dict(id='example', status='unknown')])))
        with patch.object(panel, 'confirm_continuation') as approval:
            panel.resume_workflow(result)
        approval.assert_not_called()
        self.assertIn('reconciliation', panel.status.text())
        self.assertEqual(panel.process.state(), panel.process.ProcessState.NotRunning)

    def test_history_loading_does_not_block_the_event_loop(self):
        from PySide6.QtCore import QTimer
        def slow_history(*_):
            time.sleep(.15)
            return []
        ticks = []
        with patch('build_manager.history.recent_runs', side_effect=slow_history):
            panel = self.panel()
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: ticks.append(True))
            timer.start()
            self.wait_history(panel)
            timer.stop()
        self.assertGreater(len(ticks), 3)
