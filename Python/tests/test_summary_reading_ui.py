"""Live summary updates keep evidence readable and problems directly accessible."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from tempfile import TemporaryDirectory
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.run_ui import RunView


class SummaryReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.view = RunView()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.deleteLater)
        plan = Plan('Fixture', 'Test', {}, tuple(
            Phase(key, (sys.executable, '-V'), directory.name) for key in ('check', 'other')), directory.name)
        self.view.reset(plan)
        self.view.resize(1000, 700)
        self.view.show()
        self.summary = self.view.results_workspace.flow
        self.summary.open_group('operation')
        self.view.flow.canvas.cards['check'][0].click()
        self.view.update_phase(dict(id='check', status='failed', error='Failure headline\n' + '\n'.join(
            f'Evidence line {i}' for i in range(150))))
        self.app.processEvents()

    def test_ticks_and_changed_evidence_preserve_scroll_and_selection(self):
        details = self.view.detail
        cursor = details.textCursor()
        cursor.setPosition(20)
        cursor.setPosition(30, cursor.MoveMode.KeepAnchor)
        details.setTextCursor(cursor)
        bar = details.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        value = bar.value()
        self.assertGreater(value, 0)
        selected = details.textCursor().selectedText()
        self.view.tick()
        self.view.update_phase(dict(id='other', status='running'))
        self.assertEqual(bar.value(), value)
        self.assertEqual(details.textCursor().selectedText(), selected)
        self.view.update_phase(dict(id='check', status='failed', summary='Additional evidence'))
        self.assertEqual(bar.value(), value)
        self.assertEqual(details.textCursor().selectedText(), selected)
        self.view.flow.canvas.cards['other'][0].click()
        self.assertEqual(bar.value(), 0)

    def test_failure_precedes_context_and_button_opens_step_evidence(self):
        text = self.view.detail.toPlainText()
        self.assertLess(text.index('Failure headline'), text.index('Dependencies:'))
        self.view.attention_problems.click()
        self.assertEqual(self.view.selected, 'check')
        self.assertIs(self.view.results_workspace.inspector_tabs.currentWidget(), self.view.results_workspace.details_scroll)
        self.assertIn('Failure headline', self.view.detail.toPlainText())

    def test_failed_completion_opens_causal_summary_once(self):
        self.view.inspect_summary_phase('other')
        self.view.show_logs()
        self.view.complete(dict(status='failed', seconds=3))
        self.assertIs(self.view.tabs.currentWidget(), self.view.summary_page)
        self.assertEqual(self.view.selected, 'check')
        self.assertIn('Failure headline', self.view.outcome_view.message.text())
        self.view.show_logs('other')
        self.view.tick()
        self.view.complete(dict(status='failed', seconds=3))
        self.assertIs(self.view.tabs.currentWidget(), self.view.output)
        self.assertEqual(self.view.selected, 'other')

    def test_problem_action_scopes_tests_and_selects_failure_message(self):
        case = dict(name='broken check', classname='Fixture', suite='Checks', status='failed', seconds=.1,
                    message='Expected a valid result')
        self.view.update_phase(dict(id='check', status='failed', tests=[case]))
        self.assertIn(case['message'], self.view.detail.toPlainText())
        self.view.attention_problems.click()
        self.assertEqual(self.view.selected, 'check')
        self.assertEqual(self.view.tabs.currentWidget(), self.view.tests.parentWidget())
        self.assertEqual(self.view.filter.currentText(), 'Problems')
        self.assertIsNotNone(self.view.tests.currentItem())
        self.assertIn(case['message'], self.view.test_detail.toPlainText())

    def test_summary_prefers_assertion_and_opens_exact_case(self):
        cases = [dict(name=name, classname='Fixture', suite='Checks', status=status,
                      seconds=.1, message=message)
                 for name, status, message in [('passed', 'passed', ''),
                     ('broken', 'failed', 'Traceback (most recent call last):\nAssertionError: Expected success'),
                     ('later', 'error', 'ValueError: another failure')]]
        self.view.update_phase(dict(id='check', status='failed',
            error='JUnit report contains failing tests', tests=cases))
        self.view.complete(dict(status='failed', seconds=3))
        self.assertEqual(self.view.outcome_view.message.text(), 'AssertionError: Expected success')
        self.view.search.setText('unrelated')
        self.view.outcome_view.failed_case.click()
        self.assertIs(self.view.tabs.currentWidget(), self.view.test_results)
        self.assertEqual(self.view.tests.currentItem().text(0), 'broken')
        self.assertIn('Expected success', self.view.test_detail.toPlainText())
        self.view.tests.setCurrentItem(self.view.tests.topLevelItem(2))
        requests = []
        self.view.diagnostics_requested.connect(requests.append)
        self.view.test_results.copy_case.click()
        self.assertEqual(requests, ['check'])
        self.assertEqual(self.view.selected_test_identity(), ('check', 'Fixture.later'))
        self.view.show_summary()
        self.assertEqual(self.view.selected_test_identity(), ('', ''))

    def test_blocked_summary_names_the_cause_once_and_keeps_other_failures(self):
        plan = self.view.plan
        blocked = Phase('dependent', (sys.executable, '-V'), plan.workspace,
                        dependencies=('check',), label='Dependent work')
        self.view.reset(Plan(plan.project, plan.operation, {}, (*plan.phases, blocked), plan.workspace))
        self.view.update_phase(dict(id='check', status='failed', error='Required check failed'))
        self.view.update_phase(dict(id='other', status='failed', error='Independent failure'))
        self.view.update_phase(dict(id='dependent', status='skipped'))
        self.view.complete(dict(status='failed'))
        self.view.inspect_summary_phase('dependent')
        self.app.processEvents()
        self.assertTrue(self.view.results_workspace.blocker.isHidden())
        self.assertFalse(self.view.outcome_view.blocker.isHidden())
        self.assertIn('did not run', self.view.outcome_view.message.text())
        self.assertIn('Other', self.view.outcome_view.problems.text())
        self.assertNotIn('Check', self.view.outcome_view.problems.text())
        self.view.outcome_view.blocker.click()
        self.assertEqual(self.view.selected, 'check')

    def test_timing_is_a_tests_action_only_with_reported_durations(self):
        case = dict(name='untimed', classname='Fixture', suite='Checks', status='passed',
                    seconds=None, message='')
        self.view.update_phase(dict(id='check', status='passed', tests=[case]))
        self.view.tabs.setCurrentWidget(self.view.test_results)
        self.assertTrue(self.view.test_results.timing_button.isHidden())
        self.view.update_phase(dict(id='check', status='passed', tests=[dict(case, seconds=.25)]))
        self.view.test_results.timing_button.click()
        self.assertIs(self.view.tabs.currentWidget(), self.view.test_results)
        self.assertFalse(self.view.test_results.timing_page.isHidden())
        self.assertTrue(self.view.tests.isHidden())
        self.view.test_results.timing_button.click()
        self.assertFalse(self.view.tests.isHidden())


    def test_stage_column_filter_and_timing_keep_scope_and_outcomes(self):
        cases = [dict(name=name, classname='Fixture', suite='Checks', status=status,
                      seconds=.1, message='', **({'stage':stage} if stage else {}))
                 for name, stage, status in [('startup','smoke','passed'),
                    ('editing','regression','failed'), ('soak','extended','passed'),
                    ('legacy',None,'passed')]]
        self.view.update_phase(dict(id='check', status='failed', tests=cases))
        self.assertFalse(self.view.tests.isColumnHidden(5))
        self.assertFalse(self.view.timings.isColumnHidden(5))
        self.assertEqual(self.view.tests.header().visualIndex(5), 2)
        self.assertEqual([self.view.tests.topLevelItem(i).text(5) for i in range(4)],
                         ['Smoke','Regression','Extended','Unspecified'])
        self.assertEqual(self.view.timings.topLevelItem(0).text(5), 'Smoke')
        self.view.stage_filter.setCurrentText('Smoke')
        self.view.filter.setCurrentText('Passed')
        self.assertEqual([self.view.tests.topLevelItem(i).isHidden() for i in range(4)],
                         [False,True,True,True])
        self.assertEqual(self.view.test_matches.text(), '1 / 4 shown')
        self.view.search.setText('absent')
        self.assertEqual(self.view.test_matches.text(), '0 / 4 shown')
        self.view.search.clear()
        self.view.stage_filter.setCurrentText('Unspecified')
        self.assertFalse(self.view.tests.topLevelItem(3).isHidden())
        self.view.tests.setCurrentItem(self.view.tests.topLevelItem(3))
        self.assertIn('Stage: Unspecified', self.view.test_detail.toPlainText())
        self.view.stage_filter.setCurrentText('Smoke')
        self.assertEqual(self.view.test_detail.toPlainText(), '')
        self.view.show_problems()
        self.assertEqual(self.view.stage_filter.currentText(), 'All stages')
        self.assertFalse(self.view.tests.topLevelItem(1).isHidden())

    def test_stage_only_updates_refresh_and_legacy_scope_hides_controls(self):
        case = dict(name='startup', classname='Fixture', suite='Checks', status='passed',
                    seconds=.1, message='', stage='smoke')
        self.view.update_phase(dict(id='check', status='passed', tests=[case]))
        self.view.update_phase(dict(id='check', status='passed', tests=[dict(case, stage='extended')]))
        self.assertEqual(self.view.tests.topLevelItem(0).text(5), 'Extended')
        self.view.stage_filter.setCurrentText('Smoke')
        legacy = {key:value for key,value in case.items() if key != 'stage'}
        self.view.update_phase(dict(id='check', status='passed', tests=[legacy]))
        self.assertTrue(self.view.tests.isColumnHidden(5))
        self.assertTrue(self.view.timings.isColumnHidden(5))
        self.assertTrue(self.view.stage_filter.isHidden())
        self.assertEqual(self.view.stage_filter.currentText(), 'All stages')
        self.assertFalse(self.view.tests.topLevelItem(0).isHidden())
