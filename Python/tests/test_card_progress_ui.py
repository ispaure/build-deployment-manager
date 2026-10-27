"""Card outcomes and progress reflect execution evidence, including dependencies."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication, QProgressBar
from build_manager import Phase, Plan
from build_manager.grouped_workflow_ui import GroupedFlowView
from build_manager.workflow_ui import FlowCanvas, display_states, visible_dependencies


class CardProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_automatic_device_card_has_no_approval_badge(self):
        from PySide6.QtWidgets import QLabel
        with TemporaryDirectory() as directory:
            phase = Phase('install', (sys.executable, '-V'), directory, effect='deploy', approval_required=False)
            canvas = FlowCanvas()
            self.addCleanup(canvas.close)
            canvas.reset(Plan('Fixture', 'device', {}, (phase,), directory))
            self.assertIsNone(canvas.cards['install'][0].findChild(QLabel, 'approvalBadge'))

    def test_time_share_paints_duration_in_cell_at_larger_font_sizes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
        from build_manager.workflow_ui import time_share, TimeShareDelegate, timing_duration
        tree = QTreeWidget()
        self.addCleanup(tree.close)
        tree.setColumnCount(3)
        tree.resize(600, 250)
        row = QTreeWidgetItem(['Commonutils', 'Running', ''])
        tree.addTopLevelItem(row)
        for size in (13, 20):
            font = tree.font()
            font.setPointSize(size)
            tree.setFont(font)
            time_share(tree, row, 16.37, 40)
            tree.show()
            self.app.processEvents()
            self.assertEqual(row.text(2), '16.37s')
            self.assertAlmostEqual(row.data(2, Qt.ItemDataRole.UserRole), 16.37 / 40)
            self.assertIn('40.9%', row.data(2, Qt.ItemDataRole.AccessibleTextRole))
            self.assertIsNone(tree.itemWidget(row, 2))
            self.assertIsInstance(tree.itemDelegateForColumn(2), TimeShareDelegate)
            self.assertGreaterEqual(tree.visualItemRect(row).height(), tree.fontMetrics().height())
            self.assertFalse(tree.grab().isNull())
        for seconds, expected in ((None, '—'), (0, '0s'), (.000125, '0.12ms'),
                                  (.0125, '12.5ms'), (.999, '999ms'), (1, '1s'), (120, '120s')):
            self.assertEqual(timing_duration(seconds), expected)
        time_share(tree, row, None, 40)
        self.assertIsNone(row.data(2, Qt.ItemDataRole.UserRole))
        self.assertEqual(row.text(2), '—')
        time_share(tree, row, 0, 0)
        self.assertIsNone(row.data(2, Qt.ItemDataRole.UserRole))
        self.assertEqual(row.text(2), '0s')

    def test_group_progress_tracks_completed_subtasks_and_resets(self):
        with TemporaryDirectory() as directory:
            phases = tuple(Phase(f'step-{i}', (sys.executable, '-V'), directory,
                dependencies=(f'step-{i-1}',) if i else ()) for i in range(10))
            plan = Plan('Fixture', 'Test', {}, phases, directory)
            view = GroupedFlowView()
            self.addCleanup(view.close)
            view.reset(plan, preview=False)
            card = view.canvas.cards['operation'][0]
            bar = card.findChild(QProgressBar, 'cardProgress')
            self.assertTrue(bar.isHidden())
            facts = {f'step-{i}': dict(status='passed') for i in range(4)}
            facts['step-4'] = dict(status='running')
            view.set_facts(facts)
            self.assertFalse(bar.isHidden())
            self.assertEqual((bar.value(), bar.maximum(), bar.format()), (4, 10, '4/10 steps finished'))
            view.set_facts({phase.id: dict(status='passed') for phase in phases})
            self.assertEqual(card.property('state'), 'passed')
            self.assertTrue(bar.isHidden())
            view.reset(plan, preview=True)
            self.assertTrue(view.canvas.cards['operation'][0].findChild(QProgressBar, 'cardProgress').isHidden())

    def test_live_card_and_fitted_map_geometry_stay_stable_across_updates(self):
        from build_manager.workflow_ui import WorkflowFlow
        with TemporaryDirectory() as directory:
            phases = (Phase('checks', (sys.executable, '-V'), directory),
                Phase('deliver', (sys.executable, '-V'), directory,
                      dependencies=('checks',), effect='deploy'))
            plan = Plan('Fixture', 'Test', {}, phases, directory)
            view = WorkflowFlow(graph_only=True)
            self.addCleanup(view.close)
            view.resize(900, 600)
            view.reset(plan)
            view.show()
            def geometry():
                for _ in range(3):
                    self.app.processEvents()
                return ([card.geometry() for card, _, _ in view.canvas.cards.values()],
                        view.canvas.size(), view.scroll.transform(), view.canvas.vertical)
            before = geometry()
            for status, name in (('running', 'test_short'), ('running', 'test_' + 'long_name_' * 40),
                                 ('passed', ''), ('failed', ''), ('queued', '')):
                facts = dict(checks=dict(status=status, seconds=12345,
                    current_test=dict(name=name, seconds=500) if name else None,
                    live_tests=[dict(status='passed')] * 100))
                view.set_facts(facts)
                self.assertEqual(geometry(), before)
                if name:
                    self.assertIn(name, view.canvas.cards['checks'][0].toolTip())
            view.select('checks')
            self.assertEqual(geometry(), before)

    def test_grouped_live_cards_reserve_progress_and_status_space(self):
        with TemporaryDirectory() as directory:
            phases = tuple(Phase(f'step-{i}', (sys.executable, '-V'), directory) for i in range(5))
            view = GroupedFlowView()
            self.addCleanup(view.close)
            view.resize(800, 600)
            view.reset(Plan('Fixture', 'Test', {}, phases, directory), preview=False)
            view.show()
            for _ in range(3):
                self.app.processEvents()
            card = view.canvas.cards['operation'][0]
            before = card.geometry(), view.map.transform()
            for status in ('running', 'waiting_resource', 'passed', 'failed'):
                view.set_facts({phase.id: dict(status=status, seconds=9999,
                    resource='runner-with-a-very-long-resource-name') for phase in phases})
                for _ in range(3):
                    self.app.processEvents()
                self.assertEqual((card.geometry(), view.map.transform()), before)

    def test_failure_mutes_only_dependent_work_and_keeps_it_inspectable(self):
        with TemporaryDirectory() as directory:
            phases = (Phase('check', (sys.executable, '-V'), directory),
                Phase('package', (sys.executable, '-V'), directory, dependencies=('check',)),
                Phase('deliver', (sys.executable, '-V'), directory, dependencies=('package',)),
                Phase('independent', (sys.executable, '-V'), directory),
                Phase('cleanup', (sys.executable, '-V'), directory, dependencies=('check',), always=True))
            canvas = FlowCanvas()
            self.addCleanup(canvas.close)
            plan = Plan('Fixture', 'Test', {}, phases, directory)
            canvas.reset(plan)
            canvas.update_facts(plan, {'check': dict(status='running')}, '')
            bar = canvas.cards['check'][0].findChild(QProgressBar, 'cardProgress')
            self.assertFalse(bar.isHidden())
            self.assertEqual((bar.minimum(), bar.maximum()), (0, 0))
            canvas.update_facts(plan, {'check': dict(status='error')}, '')
            self.assertTrue(bar.isHidden())
            for key in ('package', 'deliver'):
                card = canvas.cards[key][0]
                self.assertEqual(card.property('state'), 'blocked')
                self.assertTrue(card.isEnabled())
            for key in ('independent', 'cleanup'):
                self.assertEqual(canvas.cards[key][0].property('state'), 'queued')

    def test_live_case_counts_expand_inside_run_inspector_and_reset(self):
        from build_manager.run_ui import RunView
        with TemporaryDirectory() as directory:
            phase = Phase('commonutils', (sys.executable, '-V'), directory)
            plan = Plan('Fixture', 'Test', {}, (phase,), directory)
            view = RunView()
            self.addCleanup(view.close)
            view.reset(plan)
            view.flow.select('commonutils')
            case = dict(name='test_first', classname='Shared.Cases', suite='shared', status='passed',
                        seconds=.1, message='Measured details')
            view.update_phase(dict(id=phase.id, status='running', live_tests=[case], tests_provisional=True))
            row = view.substeps.topLevelItem(0)
            self.assertEqual(row.childCount(), 1)
            self.assertFalse(view.substeps.isHidden())
            row.setExpanded(True)
            view.substeps.setCurrentItem(row.child(0))
            self.assertIn('Measured details', view.test_detail.toPlainText())
            view.update_phase(dict(id=phase.id, status='running', live_tests=[case, dict(case, name='test_second')], tests_provisional=True))
            self.assertTrue(row.isExpanded())
            self.assertEqual(row.childCount(), 2)
            self.assertEqual(view.facts[phase.id]['status'], 'running')
            view.update_phase(dict(id=phase.id, status='passed', tests=[case], live_tests=[], tests_provisional=False))
            self.assertEqual(row.childCount(), 1)
            self.assertEqual(row.child(0).text(1), 'Passed')
            view.reset(plan)
            self.assertEqual(view.selected, '')
            self.assertEqual(view.substeps.topLevelItemCount(), 1)
            self.assertEqual(view.substeps.topLevelItem(0).childCount(), 0)

    def test_status_backgrounds_remain_distinct_when_switching_light_and_dark(self):
        from commonUtils.ui.appearance.theme import configured_colors, theme_palette, theme_stylesheet
        palette, stylesheet = self.app.palette(), self.app.styleSheet()
        self.addCleanup(self.app.setPalette, palette)
        self.addCleanup(self.app.setStyleSheet, stylesheet)
        with TemporaryDirectory() as directory:
            statuses = ('running', 'passed', 'failed', 'awaiting_review', 'blocked')
            phases = tuple(Phase(state, (sys.executable, '-V'), directory) for state in statuses)
            plan = Plan('Fixture', 'Test', {}, phases, directory)
            canvas = FlowCanvas()
            self.addCleanup(canvas.close)
            canvas.reset(plan)
            canvas.update_facts(plan, {state: dict(status=state) for state in statuses}, '')
            canvas.show()
            for dark in (False, True, False):
                colors = configured_colors(dark)
                self.app.setPalette(theme_palette(colors))
                self.app.setStyleSheet(theme_stylesheet(colors))
                self.app.processEvents()
                backgrounds = []
                for state in statuses:
                    card = canvas.cards[state][0]
                    background = card.grab().toImage().pixelColor(8, 8)
                    backgrounds.append(background.name())
                    self.assertEqual(background.lightness() < 128, dark, (state, background.name()))
                    self.assertGreater(abs(card.palette().text().color().lightness() - background.lightness()), 80)
                self.assertEqual(len(set(backgrounds)), len(statuses))

    def test_cleanup_completion_does_not_imply_native_success(self):
        phases = (Phase('native', (sys.executable, '-V'), '.'),
            Phase('cleanup', (sys.executable, '-V'), '.', dependencies=('native',), always=True),
            Phase('validated', (sys.executable, '-V'), '.', dependencies=('native', 'cleanup')))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        self.assertIn(('native', 'validated'), visible_dependencies(phases))
        states = display_states(plan, {'native': dict(status='failed'), 'cleanup': dict(status='passed')})
        self.assertEqual(states['validated'][0], 'blocked')


if __name__ == '__main__':
    unittest.main()
