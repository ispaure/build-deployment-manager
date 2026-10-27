"""Reduce map clutter without weakening declared scheduling or failure semantics."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.workflow_ui import (FlowCanvas, WorkflowFlow, connection_groups,
    connection_path, display_states, visible_dependencies)


def step(key, parents=(), **options):
    return Phase(key, (sys.executable, '-V'), '.', dependencies=parents, **options)


class VisualDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_common_utils_links_are_implied_through_each_test_chain(self):
        phases = (step('commonUtils'), step('B', ('commonUtils',)),
                  step('C', ('commonUtils', 'B')), step('D', ('commonUtils', 'B', 'C')))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        self.assertEqual(canvas.edges, [('commonUtils', 'B'), ('B', 'C'), ('C', 'D')])
        self.assertEqual(plan.data(), before)
        states = display_states(plan, {'commonUtils': dict(status='failed')})
        self.assertEqual(states['C'][0], 'blocked')
        self.assertIn('commonUtils', states['C'][1])
        # A filtered drawing cannot imply a connection through a hidden card.
        canvas.reset(plan, {'commonUtils', 'C'})
        self.assertEqual(canvas.edges, [('commonUtils', 'C')])

    def test_fork_join_preserves_both_branches_and_independent_prerequisites(self):
        phases = (step('A'), step('B', ('A',)), step('C', ('A',)), step('independent'),
                  step('join', ('A', 'B', 'C', 'independent')))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'),
            ('B', 'join'), ('C', 'join'), ('independent', 'join')})

    def test_selection_keeps_all_reduced_connections_painted(self):
        phases = (step('A'), step('B', ('A',)), step('C', ('A',)),
                  step('join', ('A', 'B', 'C')), step('cleanup', waits_for=('join',)))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        view = WorkflowFlow(graph_only=True)
        self.addCleanup(view.close)
        view.reset(plan, preview=True)
        view.show()
        self.app.processEvents()
        expected = {('A', 'B'), ('A', 'C'), ('B', 'join'), ('C', 'join'), ('join', 'cleanup')}
        for selected in ('', 'A', 'B', 'join', 'cleanup', ''):
            view.select(selected)
            self.assertEqual(set(view.canvas.edges), expected)
            with patch('build_manager.workflow_ui.connection_path', wraps=connection_path) as draw:
                view.canvas.grab()
            expected_groups = connection_groups(view.canvas.edges, view.canvas.positions,
                view.canvas.order_edges, view.canvas.states, view.canvas.completion_targets)
            self.assertEqual(draw.call_count, len(expected_groups))
        self.assertIn(('join', 'cleanup'), view.canvas.order_edges)
        view.set_scope({'A', 'C'})
        view.select('C')
        self.assertEqual(view.canvas.edges, [('A', 'C')])
        self.assertEqual(plan.data(), before)

    def test_shared_junction_preserves_exact_prerequisites_and_separate_semantics(self):
        positions = {'portable': (0, 0), 'desktop': (0, 2), 'host': (0, 4),
                     'build': (1, 1), 'tools': (1, 3), 'later': (2, 0)}
        edges = [(source, target) for source in ('portable', 'desktop', 'host')
                 for target in ('build', 'tools')]
        groups = connection_groups(edges, positions)
        self.assertEqual(len(groups), 1)
        self.assertEqual({(source, target) for sources, targets, _ in groups
                          for source in sources for target in targets}, set(edges))
        # Different parent sets must not acquire each other's prerequisites.
        partial = edges[:-1]
        groups = connection_groups(partial, positions)
        self.assertEqual(len(groups), 2)
        self.assertEqual({(source, target) for sources, targets, _ in groups
                          for source in sources for target in targets}, set(partial))
        for options in ({'order_edges': {('host', 'tools')}},
                        {'states': {'tools': ('blocked', '')}},
                        {'completion_targets': {'tools'}}):
            self.assertGreater(len(connection_groups(edges, positions, **options)), 1)

    def test_shared_junction_uses_straight_rail_and_horizontal_arrow_entries(self):
        starts = [QPointF(100, y) for y in (50, 150, 250)]
        ends = [QPointF(148, y) for y in (100, 200)]
        path, arrows, junctions = connection_path(starts, ends)
        self.assertEqual(len(arrows), 2)
        self.assertEqual(len(junctions), 5)
        self.assertEqual({point.x() for point in junctions}, {124})
        previous = None
        for index in range(path.elementCount()):
            element = path.elementAt(index)
            if element.isLineTo():
                self.assertTrue(element.x == previous.x or element.y == previous.y)
            previous = element
        for end, arrow in zip(ends, arrows):
            self.assertEqual(arrow[0], end)
            self.assertEqual((arrow[1].y() + arrow[2].y()) / 2, end.y())

    def test_cleanup_cannot_hide_a_success_requirement(self):
        phases = (step('A'), step('cleanup', ('A',), always=True), step('C', ('A', 'cleanup')))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'cleanup'), ('A', 'C'), ('cleanup', 'C')})
        # Cleanup needs completion, which is already implied through B.
        phases = (step('A'), step('B', ('A',)), step('cleanup', ('A', 'B'), always=True))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'B'), ('B', 'cleanup')})

    def test_cleanup_fan_in_drops_ancestors_but_keeps_independent_leaves(self):
        phases = (step('commonutils'), step('portable', ('commonutils',)),
                  step('desktop', ('commonutils',)), step('host', ('commonutils',)),
                  step('build', ('portable', 'desktop', 'host')),
                  step('tools', ('portable', 'desktop', 'host')),
                  step('ready', ('build', 'tools')),
                  step('native', ('ready',)), step('runtime', ('ready',)),
                  step('cleanup', ('commonutils', 'portable', 'desktop', 'host',
                                   'build', 'tools', 'ready', 'native', 'runtime'), always=True))
        edges = visible_dependencies(phases)
        self.assertEqual({source for source, target in edges if target == 'cleanup'}, {'native', 'runtime'})
        self.assertIn(('commonutils', 'portable'), edges)
        self.assertIn(('portable', 'build'), edges)
        # Completion-only paths can simplify cleanup, but not success gates.
        phases = (step('A'), step('B', waits_for=('A',)),
                  step('cleanup', ('A', 'B'), always=True))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('B', 'cleanup')})

    def test_completion_waits_do_not_imply_success_and_stay_visible(self):
        phases = (step('A'), step('B', waits_for=('A',)), step('C', ('A', 'B')))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
        phases = (step('A'), step('B', ('A',)), step('C', ('B',), waits_for=('A',)))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
