"""Reduce map clutter without weakening declared scheduling or failure semantics."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.workflow_ui import FlowCanvas, WorkflowFlow, dependency_path, display_states, visible_dependencies


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
            with patch('build_manager.workflow_ui.dependency_path', wraps=dependency_path) as draw:
                view.canvas.grab()
            self.assertEqual(draw.call_count, len(expected))
        self.assertIn(('join', 'cleanup'), view.canvas.order_edges)
        view.set_scope({'A', 'C'})
        view.select('C')
        self.assertEqual(view.canvas.edges, [('A', 'C')])
        self.assertEqual(plan.data(), before)

    def test_cleanup_cannot_hide_a_success_requirement(self):
        phases = (step('A'), step('cleanup', ('A',), always=True), step('C', ('A', 'cleanup')))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'cleanup'), ('A', 'C'), ('cleanup', 'C')})
        # Preserve the declared incoming relationships of an always-run target.
        phases = (step('A'), step('B', ('A',)), step('cleanup', ('A', 'B'), always=True))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'B'), ('A', 'cleanup'), ('B', 'cleanup')})

    def test_completion_waits_do_not_imply_success_and_stay_visible(self):
        phases = (step('A'), step('B', waits_for=('A',)), step('C', ('A', 'B')))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
        phases = (step('A'), step('B', ('A',)), step('C', ('B',), waits_for=('A',)))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
