"""Summary contract and desktop navigation over real retained plan data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import json
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from build_manager import Phase, Plan
from build_manager.plan_summary import captured_choices, start_scope, summary_rows
from build_manager.run_ui import RunView
from build_manager.ui import ManagerPanel
from test_journeys import integrated
from test_ui import OtherProject


class PlanSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def texts(self, widget):
        return '\n'.join(label.text() for label in widget.findChildren(QLabel) if not label.isHidden())

    def test_dispatch_and_its_dependents_never_appear_under_starts_now(self):
        plan = Plan('Hosted', 'Checks', {}, (
            Phase('dispatch', (sys.executable, '-V'), str(self.root), effect='dispatch'),
            Phase('collect', (sys.executable, '-V'), str(self.root), effect='inspect', dependencies=('dispatch',)),
        ), str(self.root / 'workspace'))
        now, later, _ = summary_rows(plan)
        self.assertEqual(now, [])
        self.assertEqual([row['keys'] for row in later], [('dispatch',), ('collect',)])
        self.assertIn('separate approval', later[0]['detail'])
        self.assertIn('dependent work waits', start_scope(plan))
        legacy = replace(plan, effect='dispatch', phases=(replace(plan.phases[0], effect='inherit'),))
        self.assertIn('confirmation before Start', summary_rows(legacy)[1][0]['detail'])
        self.assertIn('asks for confirmation', start_scope(legacy))

    def test_captured_values_follow_destination_scope_and_shared_values_appear_once(self):
        plan = integrated(self.root)
        fields = [dict(id='notes', label='Android notes', destinations=['firebase']),
                  dict(id='shared', label='Shared notes', destinations=['firebase', 'testflight'])]
        plan = replace(plan, source=dict(plan.source, dirty=True, selection='Current files',
            release_tag='1.2.3', run_overrides={'notes': 'Android release', 'shared': 'Common release'}))
        before = plan.data()
        now, later, shared = summary_rows(plan, fields)
        self.assertEqual([row['title'] for row in now][:2], ['Validate android', 'Validate ios'])
        self.assertIn('Android release', later[0]['detail'])
        self.assertNotIn('Android release', later[1]['detail'])
        self.assertEqual(shared, ['Shared notes: Common release'])
        self.assertIn('uncommitted', captured_choices(plan)[0][1])
        self.assertIn('fixed', captured_choices(plan)[0][1])
        self.assertIn('1.2.3', captured_choices(plan)[2][1])
        self.assertEqual(plan.data(), before)

    def test_review_opens_summary_and_keyboard_inspection_keeps_footer_reachable(self):
        panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(panel.close)
        panel.resize(1024, 700)
        panel.present_plan(integrated(self.root))
        panel.stages.setCurrentIndex(1)
        panel.start.setEnabled(True)
        panel.show()
        self.app.processEvents()
        workspace = panel.review_workspace
        self.assertEqual([workspace.inspector_tabs.tabText(i) for i in range(workspace.inspector_tabs.count())],
                         ['Details', 'Command', 'Plan'])
        self.assertTrue(panel.review_splitter.isVisible())
        self.assertTrue(workspace.inspector_scroll.isVisible())
        self.assertLessEqual(panel.start.mapTo(panel, panel.start.rect().bottomRight()).y(), panel.height())
        cards = workspace.flow
        button = cards.canvas.cards['platform.android'][0]
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertEqual(set(workspace.rows), {'android'})
        self.assertTrue(workspace.graph.isHidden())
        self.assertEqual(workspace.tasks.currentItem(), workspace.rows['android'])
        self.assertEqual(workspace.selected, 'android')
        cards.back.click()
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertTrue(workspace.inspector_scroll.isVisible())
        workspace.tasks.setCurrentItem(workspace.rows['android'])
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertEqual(workspace.selected, 'android')
        self.assertEqual(panel.process.state(), QProcess.ProcessState.NotRunning)
        panel.invalidate()
        self.assertFalse(panel.start.isEnabled())
        self.assertIn('fresh plan', panel.review_state.text())

    def test_run_summary_keeps_independent_approval_and_blocked_branch_visible(self):
        plan = integrated(self.root)
        journey = dict(plan.journey, destinations={name: dict(row, platforms=['android' if name == 'firebase' else 'ios'])
            for name, row in plan.journey['destinations'].items()})
        plan = replace(plan, journey=journey, phases=(plan.phases[0], plan.phases[1],
            replace(plan.phases[2], dependencies=('android',)),
            plan.phases[3], replace(plan.phases[4], dependencies=('ios',))))
        view = RunView()
        self.addCleanup(view.close)
        view.reset(plan)
        view.update_phase(dict(id='ios', status='failed', seconds=1))
        view.update_phase(dict(id='firebase', status='awaiting_review'))
        view.complete(dict(status='awaiting_review', seconds=2))
        cards = view.run_choices.flow
        self.assertEqual(cards.canvas.states['deliver.firebase'][0], 'awaiting_review')
        self.assertEqual(cards.canvas.states['deliver.testflight'][0], 'blocked')
        cards.open_group('deliver.firebase')
        self.assertIn('firebase:fixture/app/testers', view.detail.toPlainText())
        cards.open_group('deliver.testflight')
        self.assertIn('testflight:fixture/app/testers', view.detail.toPlainText())
        self.assertEqual(view.pages.currentIndex(), 0)
        view.inspect_summary_phase('ios')
        self.assertEqual(view.pages.currentIndex(), 0)
        self.assertEqual(view.selected, 'ios')
        self.assertIn('Eligible actions', view.workflow_action.text())
        view.complete(dict(status='unknown'))
        self.assertIn('will not repeat', view.workflow_action.text())

    def test_card_selection_keeps_overview_and_uses_shared_task_inspector(self):
        plan = integrated(self.root)
        environment = Phase('android.env', (sys.executable, '-V'), str(self.root), label='Check environment')
        plan = replace(plan, phases=(environment, replace(plan.phases[0], dependencies=('android.env',)), *plan.phases[1:]))
        view = RunView()
        self.addCleanup(view.close)
        view.reset(plan)
        workspace = view.run_choices
        cards = workspace.flow
        overview_ids = tuple(cards.canvas.cards)
        cards.open_group('platform.android')
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertEqual(tuple(cards.canvas.cards), overview_ids)
        self.assertEqual(set(workspace.rows), {'android.env', 'android'})
        workspace.tasks.setCurrentItem(workspace.rows['android'])
        self.assertEqual(view.selected, 'android')
        self.assertIn('Check environment', workspace.prerequisite_layout.itemAt(1).widget().full_text)
        view.update_phase(dict(id='android.env', status='passed', seconds=.2))
        self.assertEqual(workspace.selected, 'android')
        self.assertEqual(workspace.rows['android.env'].text(1), 'Passed')
        cards.all_tasks.click()
        self.assertEqual(set(workspace.rows), {phase.id for phase in plan.phases})
        cards.open_group('source')
        self.assertIn('No executable source subtasks', workspace.context_info.text())
        cards.open_group('platform.android')
        view.reset(plan)
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertEqual(workspace.selected, '')
        self.assertEqual(set(workspace.rows), {phase.id for phase in plan.phases})

    def test_review_and_run_keep_frozen_choose_work_geometry(self):
        from build_manager.grouped_workflow import retained_proposal
        from build_manager.workflow_ui import layout_positions
        from test_journeys import CAPABILITY
        plan = integrated(self.root)
        panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(panel.close)
        proposal = retained_proposal(plan, CAPABILITY)
        panel.present_plan(plan, proposal=proposal)
        review = panel.review_choices.flow
        self.assertEqual(review.grouped.phases, proposal.phases)
        self.assertEqual(review.canvas.positions, layout_positions(proposal.phases))
        # New configuration must not relabel an existing reviewed run.
        panel.configuration.current_proposal = replace(proposal, phases=proposal.phases[:1])
        panel.seed_run(plan)
        run = panel.run_view.run_choices.flow
        self.assertEqual(run.grouped.phases, proposal.phases)
        self.assertEqual(run.canvas.positions, review.canvas.positions)
        self.assertEqual(run.canvas.edges, review.canvas.edges)

    def test_start_keeps_shared_workspace_selection_and_live_reports(self):
        from build_manager.review_ui import ReviewPlanView
        plan = integrated(self.root)
        panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(panel.close)
        panel.resize(1280, 800)
        panel.present_plan(plan)
        panel.stages.setCurrentIndex(1)
        panel.show()
        self.app.processEvents()
        review = panel.review_workspace
        review.flow.open_group('platform.android')
        review.splitter.setSizes([650, 500])
        self.app.processEvents()
        panel.seed_run(plan)
        panel.stages.setCurrentIndex(2)
        self.app.processEvents()
        run = panel.run_view.run_choices
        self.assertIsInstance(run, ReviewPlanView)
        self.assertEqual(run.selected, review.selected)
        self.assertEqual(run.flow.selected, review.flow.selected)
        self.assertEqual(run.flow.pages.currentIndex(), 0)
        self.assertEqual(run.flow.canvas.positions, review.flow.canvas.positions)
        self.assertTrue(panel.stage_heading.isHidden())
        with patch('build_manager.run_ui.time.monotonic', return_value=100.):
            panel.run_view.update_phase(dict(id='android', status='running', seconds=12))
        self.assertEqual(run.selected, 'android')
        self.assertEqual(run.rows['android'].text(1), 'Running')
        self.assertIn('12.00s', run.fact_values['Elapsed'].text())
        self.assertTrue(run.plan_data.toPlainText())
        self.assertEqual(run.board.topLevelItemCount(), len(plan.phases))
        self.assertEqual(panel.process.state(), QProcess.ProcessState.NotRunning)

    def test_dormant_nested_browser_is_preserved_for_later_review(self):
        from build_manager.grouped_workflow_ui import GroupedFlowView
        phases = (Phase('first', (sys.executable, '-V'), str(self.root)),
                  Phase('second', (sys.executable, '-V'), str(self.root), dependencies=('first',)))
        view = GroupedFlowView()
        self.addCleanup(view.close)
        view.reset(Plan('Fixture', 'Checks', {}, phases, str(self.root)))
        view.open_group('operation')
        self.assertEqual(view.pages.currentIndex(), 1)
        self.assertEqual(set(view.step_flow.canvas.cards), {'first', 'second'})
        self.assertEqual(view.step_flow.canvas.edges, [('first', 'second')])
        view.close_group()
        self.assertEqual(view.pages.currentIndex(), 0)

    def test_resource_wait_names_the_contention_and_clears_when_execution_starts(self):
        plan = integrated(self.root)
        phases = tuple(replace(phase, resources={'host.mobile-build': 1}) if phase.id in {'android', 'ios'} else phase for phase in plan.phases)
        plan = replace(plan, phases=phases)
        panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(panel.close)
        panel.seed_run(plan)
        panel.session.buffer = json.dumps(dict(type='waiting', phase='android', resource='host.mobile-build',
            reason='Waiting for resource: host.mobile-build')) + '\n'
        panel.read_output()
        panel.live_update_timer.stop()
        panel.flush_live_updates()
        view = panel.run_view
        self.assertEqual(view.facts['android']['status'], 'waiting_resource')
        self.assertIn('Host mobile build', panel.session.current_phase)
        self.assertNotIn('android', view.started)
        cards = view.run_choices.flow
        self.assertIn('Host mobile build', cards.canvas.cards['platform.android'][2].text())
        cards.open_group('platform.android')
        self.assertIn('Shared resource: Host mobile build', view.selection_info.text())
        self.assertIn('Also requested by: Ios', view.selection_info.text())
        panel.update_phase(dict(id='android', status='running'))
        self.assertEqual(view.facts['android']['reason'], '')
        self.assertEqual(view.facts['android']['resource'], '')
        self.assertIn('android', view.started)
        self.assertNotIn('Waiting:', cards.canvas.cards['platform.android'][2].text())
        panel.session.buffer = json.dumps(dict(type='waiting', phase='workflow', resource='host.mobile-build',reason='wait')) + '\n'
        panel.read_output()
        self.assertNotIn('workflow', view.rows)
        self.assertIn('Host mobile build', panel.status.text())

    def test_retained_hydration_and_selection_do_not_relabel_overall_case_counts(self):
        plan = integrated(self.root)
        view = RunView()
        self.addCleanup(view.close)
        view.reset(plan, [dict(id='android', status='passed', tests=[dict(name='one', status='passed',
            suite='sample', classname='', seconds=1, message='')])])
        self.assertIn('1 reported test cases', view.overall_tests.text())
        view.inspect_summary_phase('ios')
        self.assertIn('1 reported test cases', view.overall_tests.text())
        view.reset(plan)
        self.assertIn('No individual case reports', view.overall_tests.text())
        self.assertEqual(view.pages.currentIndex(), 0)


if __name__ == '__main__':
    unittest.main()
