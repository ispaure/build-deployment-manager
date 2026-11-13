"""One card hierarchy scopes drawing, evidence and navigation without changing a plan."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from build_manager import Phase
from build_manager.run_ui import RunView
from test_journeys import integrated


def case(name, status='passed'):
    return dict(name=name, status=status, suite='Fixture', classname='', seconds=.2,
                message='Expected success' if status == 'failed' else '')


class ScopedRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        base = integrated(self.root)
        env = Phase('env', (sys.executable, '-V'), directory.name, label='Check environment')
        self.plan = replace(base, phases=(env, replace(base.phases[0], dependencies=('env',)), *base.phases[1:]))
        self.original = self.plan.data()
        self.view = RunView()
        self.addCleanup(self.view.close)
        self.view.reset(self.plan)
        self.grouped = self.view.results_workspace.flow

    def tearDown(self):
        self.assertEqual(self.plan.data(), self.original)

    def test_all_cards_keep_the_same_right_hand_inspector(self):
        self.view.resize(1200, 780)
        self.view.show()
        for key in ('deliver.testflight', 'platform.android', 'deliver.testflight'):
            self.grouped.open_group(key)
            self.app.processEvents()
            self.assertIs(self.view.results_workspace.splitter.widget(1), self.view.results_workspace.inspector)
            self.assertIs(self.grouped.content_splitter.widget(0), self.grouped.pages)
            self.assertTrue(self.view.results_workspace.inspector.isVisible())
            if key == 'deliver.testflight':
                self.assertEqual(self.grouped.pages.currentIndex(), 0)

    def test_keyboard_card_keeps_overview_and_scopes_shared_inspector(self):
        self.view.resize(1200, 780)
        self.view.show()
        self.app.processEvents()
        main = self.grouped.canvas.cards['platform.android'][0]
        main.setFocus()
        QTest.keyClick(main, Qt.Key.Key_Space)
        self.app.processEvents()
        self.assertEqual(set(self.view.results_workspace.rows), {'env', 'android'})
        self.assertEqual(self.grouped.pages.currentIndex(), 0)
        self.assertIs(self.view.results_workspace.splitter.widget(1), self.view.results_workspace.inspector)
        self.assertTrue(self.view.results_workspace.inspector.isVisible())
        self.assertTrue(self.grouped.map.isVisible())
        self.assertTrue(self.view.flow.isHidden())
        self.assertTrue(self.view.steps.isHidden())
        self.assertTrue(self.view.flow.stages_button.isHidden())
        self.assertTrue(self.view.flow.map_button.isHidden())
        self.assertEqual(self.view.pages.count(), 1)
        self.view.flow.canvas.cards['android'][0].click()
        self.assertEqual(self.view.selected, 'android')
        self.assertIn('Check environment', self.view.selection_info.text())
        self.grouped.back.click()
        self.assertEqual(self.grouped.pages.currentIndex(), 0)
        self.assertEqual(self.view.selected, '')

    def test_card_totals_tests_logs_and_files_are_scoped(self):
        self.view.update_phase(dict(id='android', status='passed', seconds=2, tests=[case('android test')],
            artifacts=[dict(path='/retained/android.xml', sha256='a'*64)]))
        self.view.update_phase(dict(id='ios', status='passed', seconds=3, tests=[case('ios test')],
            artifacts=[dict(path='/retained/ios.xml', sha256='b'*64)]))
        self.view.append_output('android', 'Android output')
        self.view.append_output('ios', 'iOS output')
        self.grouped.open_group('platform.android')
        self.view.flow.select('')
        self.assertEqual(set(self.view.scoped_facts()), {'env', 'android'})
        self.assertEqual(self.view.tests.topLevelItemCount(), 1)
        self.assertIn('Android output', self.view.log.toPlainText())
        self.assertNotIn('iOS output', self.view.log.toPlainText())
        visible = [self.view.delivered.topLevelItem(i).text(0) for i in range(self.view.delivered.topLevelItemCount())
                   if not self.view.delivered.topLevelItem(i).isHidden()]
        self.assertEqual(visible, ['android.xml'])
        self.assertIn('2 reported test cases', self.view.overall_tests.text())

    def test_substep_time_shares_use_only_the_displayed_scope(self):
        self.view.update_phase(dict(id='android', status='passed', seconds=10, tests=[case('android test')]))
        self.view.update_phase(dict(id='ios', status='passed', seconds=90, tests=[case('ios test')]))
        self.view.select_phase('android')
        self.view.refresh_subtests(force=True)
        row = self.view.substeps.topLevelItem(0)
        self.assertEqual(row.text(2), '10s')
        self.assertEqual(row.data(2, Qt.ItemDataRole.UserRole), 1)
        self.assertEqual(row.child(0).text(2), '200ms')
        self.assertEqual(row.child(0).data(2, Qt.ItemDataRole.UserRole), 1)

    def test_reused_substeps_keep_previous_durations_out_of_current_timing(self):
        self.view.update_phase(dict(id='android', status='passed', seconds=0, reused=True,
                                    reuse=dict(original_seconds=10), tests=[case('cached test')]))
        self.view.select_phase('android')
        self.view.refresh_subtests(force=True)
        row = self.view.substeps.topLevelItem(0)
        self.assertEqual(row.text(1), 'Reused')
        for item, previous in ((row, '10s'), (row.child(0), '200ms')):
            self.assertEqual(item.text(2), '—')
            self.assertIsNone(item.data(2, Qt.ItemDataRole.UserRole))
            self.assertIn('Previous run: ' + previous, item.toolTip(2))

    def test_running_and_never_started_timings_match_graph_and_inspector(self):
        with patch('build_manager.run_state.time.monotonic', return_value=100):
            self.view.update_phase(dict(id='env', status='running'))
        self.grouped.open_group('platform.android')
        with patch('build_manager.run_state.time.monotonic', return_value=112):
            self.view.tick()
            self.assertIn('12.00s', self.view.flow.canvas.cards['env'][1].text())
            self.assertIn('12.00s', self.view.selection_info.text())
            self.assertIn('12.00s', self.view.detail.toPlainText())
            self.assertIn('12.00s', self.grouped.canvas.cards['platform.android'][2].text())
        self.view.update_phase(dict(id='env', status='failed', seconds=12))
        self.view.flow.canvas.cards['android'][0].click()
        self.assertEqual(self.view.flow.canvas.states['android'][0], 'blocked')
        self.assertIn('Not started', self.view.selection_info.text())
        self.assertIn('Not started', self.view.flow.canvas.cards['android'][1].text())
        self.view.update_phase(dict(id='android', status='skipped', seconds=0))
        self.assertIn('Not started', self.view.detail.toPlainText())
        self.assertNotIn('0.00s', self.view.flow.canvas.cards['android'][1].text())
        task = self.view.results_workspace.rows['android']
        self.assertEqual(task.text(2), '—')
        self.assertEqual(task.toolTip(2), 'Not started')

    def test_external_prerequisites_navigate_to_their_own_card(self):
        self.grouped.open_group('deliver.firebase')
        self.assertEqual(set(self.view.results_workspace.rows), {'firebase'})
        self.assertEqual(self.view.results_workspace.prerequisite_layout.itemAt(1).widget().full_text, 'Prepare')
        self.view.results_workspace.prerequisite_layout.itemAt(1).widget().click()
        self.assertEqual(self.view.selected, 'prepare')
        self.assertIn('prepare', self.view.flow.canvas.cards)
        self.view.update_phase(dict(id='ios', status='failed', error='Gate failed'))
        self.grouped.open_group('deliver.firebase')
        self.view.blocking_step.click()
        self.assertEqual(self.view.selected, 'ios')
        self.assertEqual(set(self.view.results_workspace.rows), {'ios'})
        self.assertIn('Gate failed', self.view.detail.toPlainText())

    def test_delivery_includes_prepared_inputs_and_keeps_file_navigation_local(self):
        self.view.update_phase(dict(id='prepare', status='passed', seconds=1,
            artifacts=[dict(path='/retained/App.apk', sha256='a'*64)]))
        self.grouped.open_group('deliver.firebase')
        visible = [self.view.delivered.topLevelItem(i) for i in range(self.view.delivered.topLevelItemCount())
                   if not self.view.delivered.topLevelItem(i).isHidden()]
        artifact = next(row for row in visible if row.text(0) == 'App.apk')
        self.assertTrue(any('firebase' in row.text(0) for row in visible))
        self.assertFalse(any('testflight' in row.text(0) for row in visible))
        self.view.inspect_delivered(artifact)
        self.assertEqual(self.view.selected, 'prepare')
        self.assertIn('a'*64, self.view.detail.toPlainText())

    def test_startup_error_opens_run_evidence_without_faking_a_step_failure(self):
        self.view.inspect_summary_phase('android')
        self.view.unverified('Runner could not import its dependencies')
        self.assertEqual(self.grouped.pages.currentIndex(), 0)
        self.assertIs(self.view.tabs.currentWidget(), self.view.summary_page)
        self.assertFalse(self.view.selected)
        self.assertEqual(self.view.outcome_view.heading.text(), 'Run evidence incomplete')
        self.assertIn('Runner could not import', self.view.detail.toPlainText())
        self.assertTrue(all(row['status'] == 'queued' for row in self.view.facts.values()))

    def test_rehydrated_running_duration_does_not_restart_at_zero(self):
        with patch('build_manager.run_state.time.monotonic', return_value=100):
            self.view.reset(self.plan, [dict(id='env', status='running', seconds=25)])
            self.view.results_workspace.flow.open_group('platform.android')
            self.view.tick()
            self.assertIn('25.00s', self.view.flow.canvas.cards['env'][1].text())
            self.assertIn('25.00s', self.view.selection_info.text())

    def test_external_completion_wait_is_retained_in_inspector_without_false_edge(self):
        admit = Phase('admit', (sys.executable, '-V'), str(self.root), waits_for=('ios',), always=True)
        plan = replace(self.plan, phases=(self.plan.phases[0], self.plan.phases[2], admit,
            replace(self.plan.phases[1], dependencies=('admit',)), *self.plan.phases[3:]))
        self.view.reset(plan)
        self.view.results_workspace.flow.open_group('platform.android')
        self.assertEqual(set(self.view.results_workspace.rows), {'admit', 'android'})
        self.view.flow.canvas.cards['admit'][0].click()
        self.assertIn(('ios', 'admit'), self.view.flow.canvas.edges)
        self.assertIn('ios', self.view.detail.toPlainText())
        self.assertIn('wait for completion', self.view.results_workspace.prerequisite_layout.itemAt(1).widget().full_text)

    def test_rehydration_failure_navigation_and_reset_keep_one_inspector(self):
        report = [dict(id='env', status='passed', seconds=1),
                  dict(id='android', status='failed', seconds=2, tests=[case('broken', 'failed')])]
        for _ in range(2):
            self.view.reset(self.plan, report)
            self.view.inspect_summary_phase('firebase')
            self.view.complete(dict(status='failed', seconds=3))
            self.assertEqual(self.view.selected, 'android')
            self.assertIs(self.view.tabs.currentWidget(), self.view.summary_page)
            self.view.outcome_view.failed_case.click()
            self.assertEqual(self.view.tests.currentItem().text(0), 'broken')
            self.assertIn('Expected success', self.view.test_detail.toPlainText())
            self.assertIn('android', self.view.results_workspace.rows)
            self.assertIs(self.view.results_workspace.splitter.widget(1), self.view.results_workspace.inspector)
            self.app.processEvents()
        self.view.reset(self.plan)
        self.view.results_workspace.flow.open_group('source')
        self.assertTrue(self.view.flow.isHidden())
        self.assertIn('No executable source subtasks', self.view.detail.toPlainText())

    def test_preflight_prefers_first_captured_error_and_routes_to_its_logs(self):
        error = 'Error: required synthetic tool was not found'
        log = 'Checking workspace\n' + error + '\nChecked metadata'
        self.view.phase_log_reader = lambda key: log
        self.view.update_phase(dict(id='env', status='failed', exit_code=2, log='env.log',
                                    summary='Checked metadata'))
        self.view.update_phase(dict(id='android', status='skipped', reason='dependency did not pass'))
        self.view.inspect_summary_phase('android')
        self.assertIn('Check environment', self.view.outcome_view.message.text())
        self.view.outcome_view.blocker.click()
        self.assertEqual(self.view.selected, 'env')
        self.view.complete(dict(status='failed', seconds=3))
        self.assertIn(error, self.view.outcome_view.message.text())
        self.assertIn('From captured logs', self.view.outcome_view.message.text())
        self.view.outcome_view.logs.click()
        self.assertEqual(self.view.selected, 'env')
        self.assertIs(self.view.tabs.currentWidget(), self.view.output)
        self.assertEqual(self.view.log.toPlainText(), log)

    def test_missing_declared_junit_report_is_an_available_tests_destination(self):
        env = replace(self.plan.phases[0], artifact_types={'result.xml': 'junit'}, artifacts=('result.xml',))
        self.view.reset(replace(self.plan, phases=(env, *self.plan.phases[1:])))
        self.view.update_phase(dict(id='env', status='failed', error='JUnit report could not be collected'))
        self.view.complete(dict(status='failed'))
        self.view.tabs.setCurrentWidget(self.view.test_results)
        self.assertIs(self.view.tabs.currentWidget(), self.view.test_results)
        self.assertIn('No cases are available', self.view.test_summary.text())
        self.assertTrue(self.view.test_results.timing_button.isHidden())

    def test_explicit_logs_open_rechecks_retained_file_after_cleanup(self):
        log = self.root / 'env.log'
        log.write_text('First retained log')
        self.view.phase_log_reader = lambda key: log.read_text()
        self.view.update_phase(dict(id='env', status='failed', log=log.name))
        self.view.complete(dict(status='failed'))
        self.view.show_logs('env')
        self.assertEqual(self.view.log.toPlainText(), 'First retained log')
        log.unlink()
        self.view.tick()
        self.assertEqual(self.view.log.toPlainText(), 'First retained log')
        self.view.show_summary()
        self.view.outcome_view.logs.click()
        self.assertEqual(self.view.log.toPlainText(), '')
        self.assertIn('log file is missing', self.view.log_notice.text())

    def test_timer_before_first_plan_is_harmless(self):
        view = RunView()
        self.addCleanup(view.close)
        view.tick()

    def test_controller_error_without_plan_has_summary_and_runner_logs(self):
        view = RunView()
        self.addCleanup(view.close)
        view.unverified('The operation process could not start.')
        view.append_output(None, 'Synthetic controller stderr')
        self.assertEqual(view.outcome_view.heading.text(), 'Run evidence incomplete')
        self.assertIn('could not start', view.outcome_view.message.text())
        self.assertFalse(view.outcome_view.copy.isHidden())
        view.outcome_view.logs.click()
        self.assertIs(view.tabs.currentWidget(), view.output)
        self.assertIn('controller stderr', view.log.toPlainText())
        self.assertFalse(view.facts)


if __name__ == '__main__':
    unittest.main()
