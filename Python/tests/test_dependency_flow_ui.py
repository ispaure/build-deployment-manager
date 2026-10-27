"""Dependency graph inspection and nested destination options are presentation only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.configuration_ui import ConfigurationView
from build_manager.run_ui import RunView
from build_manager.ui import ManagerPanel
from build_manager.workflow_ui import display_states, layout_positions
from test_ui import OtherProject
from test_journeys import CAPABILITY, integrated


def report_case(name, seconds, state='passed'):
    return dict(name=name, seconds=seconds, status=state, suite='Sample', classname='Tests', message='failure detail' if state == 'failed' else '')


class DependencyFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_large_plan_stages_retain_exact_steps_and_sync_with_map(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from build_manager.workflow_ui import WorkflowFlow
        with TemporaryDirectory() as directory:
            phases = [Phase('source', (sys.executable, '-V'), directory, section='source', effect='inspect')]
            for index in range(39):
                phases.append(Phase(f'check-{index}', (sys.executable, '-V'), directory,
                    dependencies=(phases[-1].id,), label=f'Check suite {index + 1}'))
            phases.extend((Phase('package', (sys.executable, '-V'), directory,
                dependencies=('check-38',), effect='build'),
                Phase('deliver', (sys.executable, '-V'), directory,
                    dependencies=('package',), effect='upload')))
            plan = Plan('Fixture', 'Review', {}, tuple(phases), directory)
            original = plan.data()
            flow = WorkflowFlow(); flow.resize(850, 600); flow.reset(plan, preview=True); flow.show()
            self.addCleanup(flow.close)
            self.app.processEvents()
            self.assertIs(flow.views.currentWidget(), flow.browser)
            self.assertEqual(set(flow.browser.steps), {phase.id for phase in phases})
            self.assertFalse(flow.browser.groups['Checks'].isExpanded())
            self.assertIn('39 steps', flow.browser.groups['Checks'].text(0))
            self.assertIn('separate approval', flow.browser.groups['Delivery / publication'].text(2))
            group = flow.browser.groups['Checks']
            flow.browser.setCurrentItem(group)
            QTest.keyClick(flow.browser, Qt.Key.Key_Right)
            self.assertTrue(group.isExpanded())
            flow.browser.setCurrentItem(flow.browser.steps['check-38'])
            self.assertEqual(flow.selected, 'check-38')
            flow.map_button.click()
            self.assertIs(flow.views.currentWidget(), flow.scroll)
            self.assertTrue(flow.canvas.cards['check-38'][0].isChecked())
            flow.canvas.cards['deliver'][0].click()
            flow.stages_button.click()
            self.assertEqual(flow.browser.currentItem(), flow.browser.steps['deliver'])
            self.assertTrue(flow.browser.groups['Delivery / publication'].isExpanded())
            flow.whole.click()
            self.assertEqual(flow.selected, '')
            flow.set_facts({'check-0': dict(status='failed')})
            # Preview never predicts execution; run mode does explain blocked work.
            self.assertEqual(flow.browser.steps['check-1'].text(1), 'Planned')
            flow.reset(plan)
            flow.set_facts({'check-0': dict(status='failed')})
            self.assertEqual(flow.browser.steps['check-1'].text(1), 'Blocked')
            self.assertIn('blocked', flow.browser.groups['Checks'].text(1))
            self.assertEqual(plan.data(), original)

    def test_destination_options_follow_their_checkbox_and_submit_only_active_inputs(self):
        with TemporaryDirectory() as directory:
            project = OtherProject(Path(directory))
            project.journey_capability = deepcopy(CAPABILITY)
            project.run_fields = [dict(id='firebase.notes', label='Android notes', destinations=['firebase']),
                                  dict(id='ios.notes', label='Apple notes', destinations=['testflight'])]
            view = ConfigurationView(project)
            try:
                view.goal.setCurrentIndex(view.goal.findData('deliver'))
                view.destination_checks['firebase'].setChecked(True)
                fields = view.run_fields
                self.assertIs(fields.field_forms['firebase.notes'], view.destination_forms['firebase'])
                self.assertFalse(view.destination_options['firebase'].isHidden())
                self.assertTrue(view.destination_options['testflight'].isHidden())
                fields.controls['firebase.notes'].setText('Android update')
                fields.controls['ios.notes'].setText('Apple update')
                self.assertEqual(fields.values(), {'firebase.notes': 'Android update'})
                view.destination_checks['testflight'].setChecked(True)
                self.assertEqual(fields.values()['ios.notes'], 'Apple update')
                view.destination_checks['firebase'].setChecked(False)
                self.assertEqual(fields.values(), {'ios.notes': 'Apple update'})
                view.destination_checks['firebase'].setChecked(True)
                self.assertEqual(fields.values()['firebase.notes'], 'Android update')
                view.goal.setCurrentIndex(view.goal.findData('validate'))
                self.assertEqual(fields.values(), {})
                self.assertTrue(view.destination_options['firebase'].isHidden())
            finally:
                view.run_fields.stop(); view.close()

    def test_shared_fields_remain_single_and_advanced_fields_return_to_their_form(self):
        with TemporaryDirectory() as directory:
            project = OtherProject(Path(directory)); project.journey_capability = deepcopy(CAPABILITY)
            project.run_fields = [dict(id='shared', label='Shared notes', destinations=['firebase', 'testflight']),
                                  dict(id='one', label='Notes', destinations=['firebase'], operations=['Test'])]
            view = ConfigurationView(project)
            try:
                view.goal.setCurrentIndex(view.goal.findData('deliver'))
                view.destination_checks['firebase'].setChecked(True)
                self.assertIs(view.run_fields.field_forms['shared'], view.run_fields.form)
                self.assertIs(view.run_fields.field_forms['one'], view.destination_forms['firebase'])
                view.run_fields.controls['one'].setText('Preserved')
                view.goal.setCurrentIndex(view.goal.findData('advanced'))
                self.assertIs(view.run_fields.field_forms['one'], view.run_fields.form)
                self.assertEqual(view.run_fields.values(), {'one': 'Preserved'})
            finally:
                view.run_fields.stop(); view.close()

    def test_unavailable_destinations_are_explained_and_cannot_be_selected(self):
        with TemporaryDirectory() as directory:
            from PySide6.QtWidgets import QLabel
            project = OtherProject(Path(directory)); project.journey_capability = deepcopy(CAPABILITY)
            project.journey_capability['unavailable_destinations'] = [dict(label='Development devices', reason='Artifact review is not supported yet.')]
            view = ConfigurationView(project)
            try:
                self.assertEqual(set(view.destination_checks), {'firebase', 'testflight'})
                self.assertTrue(any('Development devices' in row.text() and 'not supported' in row.text()
                    for row in view.sections['delivery'].findChildren(QLabel)))
            finally:
                view.run_fields.stop(); view.close()

    def test_left_to_right_columns_share_a_vertical_center_after_resize_and_reset(self):
        from build_manager.workflow_ui import FlowCanvas
        with TemporaryDirectory() as directory:
            def step(name, parents=()):
                return Phase(name, (sys.executable, '-V'), directory, dependencies=parents)
            plan = Plan('Fixture', 'Test', {}, (step('source'), step('android', ('source',)),
                step('ios', ('source',)), step('firebase', ('android',)),
                step('iphone', ('ios',)), step('ipad', ('ios',))), directory)
            canvas = FlowCanvas(); canvas.resize(1000, 900); canvas.reset(plan); canvas.show()
            try:
                for width in (1000, 1250):
                    canvas.resize(width, 900); self.app.processEvents()
                    for source, target in canvas.edges:
                        self.assertLess(canvas.cards[source][0].geometry().right(), canvas.cards[target][0].geometry().left())
                    centers = {}
                    for key, (level, _) in canvas.positions.items():
                        centers.setdefault(level, []).append(canvas.cards[key][0].geometry().center().y())
                    axes = [sum(row) / len(row) for row in centers.values()]
                    self.assertLessEqual(max(axes) - min(axes), 1)
                canvas.reset(replace(plan, phases=plan.phases[:1])); self.app.processEvents()
                self.assertLessEqual(abs(canvas.cards['source'][0].geometry().center().x() - canvas.rect().center().x()), 1)
                self.assertLess(canvas.headers[0].geometry().bottom(), canvas.cards['source'][0].geometry().top())
            finally:
                canvas.close()

    def test_layout_preserves_fork_join_edges_and_cleanup_is_not_predicted_blocked(self):
        with TemporaryDirectory() as directory:
            plan = integrated(Path(directory))
            cleanup = Phase('cleanup', (sys.executable, '-V'), directory, dependencies=('ios',), always=True)
            independent = Phase('independent', (sys.executable, '-V'), directory)
            plan = replace(plan, phases=(*plan.phases, cleanup, independent))
            positions = layout_positions(plan.phases)
            self.assertEqual(positions['android'][0], positions['ios'][0])
            self.assertNotEqual(positions['android'][1], positions['ios'][1])
            for phase in plan.phases:
                for dependency in phase.dependencies:
                    self.assertGreater(positions[phase.id][0], positions[dependency][0])
            facts = {'ios': dict(status='failed')}
            original = deepcopy(facts)
            states = display_states(plan, facts)
            self.assertEqual(states['prepare'][0], 'blocked')
            self.assertEqual(states['firebase'][0], 'blocked')
            self.assertEqual(states['testflight'][0], 'blocked')
            self.assertEqual(states['cleanup'][0], 'queued')
            self.assertEqual(states['independent'][0], 'queued')
            self.assertEqual(facts, original)
            self.assertEqual(display_states(plan, facts, preview=True)['prepare'][0], 'planned')

    def test_card_selection_scopes_tests_timings_and_output_and_stays_live(self):
        with TemporaryDirectory() as directory:
            plan = integrated(Path(directory)); view = RunView(); view.reset(plan)
            try:
                view.update_phase(dict(id='android', status='passed', seconds=2, tests=[report_case('android-case', 2)]))
                view.update_phase(dict(id='ios', status='running'))
                view.append_output('android', 'Android only')
                view.append_output('ios', 'Apple only')
                view.show_timings()
                chosen_tab = view.tabs.currentWidget()
                view.flow.canvas.cards['android'][0].click()
                self.assertEqual(view.selected, 'android')
                self.assertIs(view.tabs.currentWidget(), chosen_tab)
                self.assertEqual(view.tests.topLevelItemCount(), 1)
                self.assertEqual(view.timings.topLevelItem(0).text(0), 'android-case')
                view.tests.setCurrentItem(view.tests.topLevelItem(0))
                self.assertIn('android-case', view.test_detail.toPlainText())
                self.assertIn('Android only', view.log.toPlainText())
                self.assertNotIn('Apple only', view.log.toPlainText())
                view.inspect_summary_phase('ios')
                self.assertIn('Running', view.selection_info.text())
                self.assertEqual(view.tests.topLevelItemCount(), 0)
                self.assertEqual(view.test_detail.toPlainText(), '')
                view.update_phase(dict(id='ios', status='failed', seconds=1, tests=[report_case('ios-case', 1, 'failed')]))
                self.assertIn('Failed', view.selection_info.text())
                self.assertEqual(view.tests.topLevelItemCount(), 1)
                view.inspect_summary_phase('prepare')
                card = view.flow.canvas.cards['prepare'][0]
                self.assertEqual(card.property('state'), 'blocked')
                self.assertTrue(card.isEnabled())
                card.click()
                self.assertIn('Will not run', view.selection_info.text())
                self.assertIn('ios', view.selection_info.text())
                view.flow.whole.click()
                self.assertEqual(view.tests.topLevelItemCount(), 0)
                self.assertNotIn('Android only', view.log.toPlainText())
                self.assertNotIn('Apple only', view.log.toPlainText())
                self.assertFalse(view.selected)
                view.reset(plan)
                self.assertEqual(view.tests.topLevelItemCount(), 0)
                self.assertFalse(view.selected)
                self.assertNotIn('Apple only', view.log.toPlainText())
            finally:
                view.close()

    def test_review_card_inspection_does_not_execute_and_explains_delivery_and_cleanup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); project = OtherProject(root); panel = ManagerPanel(project)
            plan = integrated(root)
            try:
                panel.present_plan(plan)
                self.assertEqual(set(panel.review_flow.canvas.edges),
                    {(key, phase.id) for phase in plan.phases for key in phase.dependencies})
                panel.review_flow.canvas.cards['firebase'][0].click()
                self.assertIn('firebase:fixture/app/testers', panel.review_workspace.fact_values['Delivery'].text())
                self.assertIn('separate approval', panel.review_workspace.fact_values['Delivery'].text().lower())
                self.assertFalse((root / 'firebase.json').exists())
                self.assertFalse((root / 'package.bin').exists())
                panel.review_flow.whole.click()
                self.assertTrue(panel.review_workspace.error_panel.isHidden())
                self.assertTrue(panel.review_workspace.fact_panel.isHidden())
            finally:
                panel.close()

    def test_real_executor_failure_mutes_descendants_but_still_runs_cleanup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); marker = root / 'cleaned'
            project = OtherProject(root)
            phases = (Phase('gate', (sys.executable, '-c', 'raise SystemExit(1)'), directory),
                Phase('dependent', (sys.executable, '-c', 'pass'), directory, dependencies=('gate',)),
                Phase('leaf', (sys.executable, '-c', 'pass'), directory, dependencies=('dependent',)),
                Phase('cleanup', (sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()'),
                      directory, dependencies=('leaf',), always=True))
            project.make_plan = lambda *a, **k: Plan('Fixture', 'Test', {}, phases, str(root / 'workspace'))
            panel = ManagerPanel(project)
            try:
                panel.inspect_plan()
                deadline = time.monotonic() + 10
                while panel.preparing:
                    self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
                self.assertIsNotNone(panel.plan)
                panel.run_plan()
                while panel.cancel.isEnabled():
                    self.app.processEvents(); time.sleep(.005); self.assertLess(time.monotonic(), deadline)
                self.assertTrue(marker.exists())
                self.assertEqual(panel.run_view.flow.canvas.states['dependent'][0], 'skipped')
                self.assertEqual(panel.run_view.flow.canvas.states['leaf'][0], 'skipped')
                self.assertEqual(panel.run_view.flow.canvas.states['cleanup'][0], 'passed')
                panel.run_view.inspect_summary_phase('leaf')
                self.assertIn('dependency did not pass', panel.run_view.selection_info.text())
                panel.run_view.inspect_summary_phase('gate')
                self.assertIn('raise SystemExit(1)', panel.run_view.phases['gate'].argv[-1])
            finally:
                panel.close()

    def test_retained_step_logs_stay_inside_run_and_keyboard_selects_cards(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        with TemporaryDirectory() as directory:
            root = Path(directory); project = OtherProject(root); panel = ManagerPanel(project)
            plan = project.make_plan()
            try:
                panel.result = root / 'retained' / 'result.json'
                panel.result.parent.mkdir()
                (panel.result.parent / 'example.log').write_text('Captured step output')
                panel.seed_run(plan, [dict(id='example', status='passed', log='example.log')])
                card = panel.run_view.flow.canvas.cards['example'][0]
                QTest.keyClick(card, Qt.Key.Key_Space)
                self.assertEqual(panel.run_view.selected, 'example')
                self.assertEqual(panel.run_view.log.toPlainText(), 'Captured step output')
                panel.run_view.facts['example']['log'] = '../outside.log'
                with self.assertRaisesRegex(ValueError, 'inside the retained run'):
                    panel.read_phase_log('example')
                panel.run_view.facts['example']['log'] = {'invalid': True}
                with self.assertRaisesRegex(ValueError, 'Invalid step log'):
                    panel.read_phase_log('example')
            finally:
                panel.close()

    def test_switching_from_failed_card_to_approval_or_unknown_replaces_guidance(self):
        with TemporaryDirectory() as directory:
            plan = integrated(Path(directory)); view = RunView(); view.reset(plan)
            try:
                view.update_phase(dict(id='android', status='passed'))
                view.update_phase(dict(id='ios', status='passed'))
                view.update_phase(dict(id='prepare', status='passed'))
                view.update_phase(dict(id='firebase', status='failed'))
                view.update_phase(dict(id='testflight', status='awaiting_review'))
                view.flow.select('firebase')
                self.assertIn('This step failed', view.next_action.text())
                view.flow.select('testflight')
                self.assertIn('needs your approval', view.next_action.text())
                view.update_phase(dict(id='testflight', status='unknown'))
                self.assertIn('unknown outcome', view.next_action.text())
                view.run_choices.flow.all_tasks.click()
                self.assertEqual(set(view.run_choices.rows), {phase.id for phase in plan.phases})
                self.assertEqual(view.run_choices.selected, '')
            finally:
                view.close()
