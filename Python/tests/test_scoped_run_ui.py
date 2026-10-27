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
        self.grouped = self.view.run_choices.flow

    def tearDown(self):
        self.assertEqual(self.plan.data(), self.original)

    def test_all_cards_keep_the_same_right_hand_inspector(self):
        self.view.resize(1200, 780)
        self.view.show()
        for key in ('deliver.testflight', 'platform.android', 'deliver.testflight'):
            self.grouped.open_group(key)
            self.app.processEvents()
            self.assertIs(self.view.run_choices.splitter.widget(1), self.view.run_choices.inspector)
            self.assertIs(self.grouped.content_splitter.widget(0), self.grouped.pages)
            self.assertTrue(self.view.run_choices.inspector.isVisible())
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
        self.assertEqual(set(self.view.run_choices.rows), {'env', 'android'})
        self.assertEqual(self.grouped.pages.currentIndex(), 0)
        self.assertIs(self.view.run_choices.splitter.widget(1), self.view.run_choices.inspector)
        self.assertTrue(self.view.run_choices.inspector.isVisible())
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

    def test_running_and_never_started_timings_match_graph_and_inspector(self):
        with patch('build_manager.run_ui.time.monotonic', return_value=100):
            self.view.update_phase(dict(id='env', status='running'))
        self.grouped.open_group('platform.android')
        with patch('build_manager.run_ui.time.monotonic', return_value=112):
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

    def test_external_prerequisites_navigate_to_their_own_card(self):
        self.grouped.open_group('deliver.firebase')
        self.assertEqual(set(self.view.run_choices.rows), {'firebase'})
        self.assertEqual(self.view.run_choices.prerequisite_layout.itemAt(1).widget().full_text, 'Prepare')
        self.view.run_choices.prerequisite_layout.itemAt(1).widget().click()
        self.assertEqual(self.view.selected, 'prepare')
        self.assertIn('prepare', self.view.flow.canvas.cards)
        self.view.update_phase(dict(id='ios', status='failed', error='Gate failed'))
        self.grouped.open_group('deliver.firebase')
        self.view.blocking_step.click()
        self.assertEqual(self.view.selected, 'ios')
        self.assertEqual(set(self.view.run_choices.rows), {'ios'})
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
        self.view.unverified('Runner could not import its dependencies')
        self.view.show_problems()
        self.assertEqual(self.grouped.pages.currentIndex(), 0)
        self.assertIn('Runner could not import', self.view.detail.toPlainText())
        self.assertTrue(all(row['status'] == 'queued' for row in self.view.facts.values()))

    def test_rehydrated_running_duration_does_not_restart_at_zero(self):
        with patch('build_manager.run_ui.time.monotonic', return_value=100):
            self.view.reset(self.plan, [dict(id='env', status='running', seconds=25)])
            self.view.run_choices.flow.open_group('platform.android')
            self.view.tick()
            self.assertIn('25.00s', self.view.flow.canvas.cards['env'][1].text())
            self.assertIn('25.00s', self.view.selection_info.text())

    def test_external_completion_wait_is_retained_in_inspector_without_false_edge(self):
        admit = Phase('admit', (sys.executable, '-V'), str(self.root), waits_for=('ios',), always=True)
        plan = replace(self.plan, phases=(self.plan.phases[0], self.plan.phases[2], admit,
            replace(self.plan.phases[1], dependencies=('admit',)), *self.plan.phases[3:]))
        self.view.reset(plan)
        self.view.run_choices.flow.open_group('platform.android')
        self.assertEqual(set(self.view.run_choices.rows), {'admit', 'android'})
        self.view.flow.canvas.cards['admit'][0].click()
        self.assertIn(('ios', 'admit'), self.view.flow.canvas.edges)
        self.assertIn('ios', self.view.detail.toPlainText())
        self.assertIn('wait for completion', self.view.run_choices.prerequisite_layout.itemAt(1).widget().full_text)

    def test_rehydration_failure_navigation_and_reset_keep_one_inspector(self):
        report = [dict(id='env', status='passed', seconds=1),
                  dict(id='android', status='failed', seconds=2, tests=[case('broken', 'failed')])]
        for _ in range(2):
            self.view.reset(self.plan, report)
            self.view.complete(dict(status='failed', seconds=3))
            self.view.show_problems()
            self.assertEqual(self.view.selected, 'android')
            self.assertEqual(self.view.tests.currentItem().text(0), 'broken')
            self.assertIn('Expected success', self.view.test_detail.toPlainText())
            self.assertIn('android', self.view.run_choices.rows)
            self.assertIs(self.view.run_choices.splitter.widget(1), self.view.run_choices.inspector)
            self.app.processEvents()
        self.view.reset(self.plan)
        self.view.run_choices.flow.open_group('source')
        self.assertTrue(self.view.flow.isHidden())
        self.assertIn('No executable source subtasks', self.view.detail.toPlainText())

    def test_timer_before_first_plan_is_harmless(self):
        view = RunView()
        self.addCleanup(view.close)
        view.tick()


if __name__ == '__main__':
    unittest.main()
