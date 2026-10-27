"""Choose-work proportions and review dependency maps remain usable and read-only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.ui import ManagerPanel
from build_manager.workflow_ui import dependency_path
from test_ui import OtherProject
from test_journeys import CAPABILITY, integrated


class ChooseWorkLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        project = OtherProject(self.root)
        project.journey_capability = deepcopy(CAPABILITY)
        self.panel = ManagerPanel(project)
        self.addCleanup(self.panel.close)

    def test_tabs_belong_to_editor_warnings_follow_workspace_and_map_gets_width(self):
        panel = self.panel
        panel.resize(1800, 1000)
        panel.show()
        view = panel.configuration
        view.goal_buttons['deliver'].click()
        panel.platform_checks['ios'].setChecked(True)
        panel.destination_checks['firebase'].setChecked(True)
        for _ in range(5):
            self.app.processEvents()
        for key, label in [('source', 'Source'), ('platforms', 'Platforms (1)'),
                           ('delivery', 'Delivery (1)'), ('advanced', 'Options')]:
            index = view.config_tabs.indexOf(view.config_pages[key])
            self.assertEqual(view.config_tabs.tabText(index), label)
        self.assertTrue(view.config_tabs.tabBar().isVisible())
        self.assertTrue(view.editor_pane.isAncestorOf(view.config_tabs.tabBar()))
        left, right = view.splitter.sizes()
        self.assertGreaterEqual(right / (left + right), .70)
        self.assertTrue(view.blocker_strip.isVisible())
        self.assertGreaterEqual(view.blocker_strip.mapTo(view, QPoint()).y(),
                                view.splitter.geometry().bottom())
        # Repair remains actionable from the separate warning area.
        next(iter(view.blocker_actions.values())).click()
        self.assertGreaterEqual(view.config_tabs.currentIndex(), 0)

    def test_review_card_opens_exact_fork_join_map_and_preserves_plan(self):
        base = integrated(self.root)
        environment = Phase('environment', (sys.executable, '-V'), str(self.root), label='Check environment')
        branch = Phase('parallel', (sys.executable, '-V'), str(self.root), dependencies=('environment',))
        plan = replace(base, phases=(environment, branch,
            replace(base.phases[0], dependencies=('environment', 'parallel')), *base.phases[1:]))
        before = plan.data()
        self.panel.present_plan(plan)
        self.panel.stages.setCurrentIndex(1)
        self.panel.resize(1500, 900)
        self.panel.show()
        cards = self.panel.review_choices.flow
        cards.open_group('platform.android')
        for _ in range(5):
            self.app.processEvents()
        flow = self.panel.review_workspace.graph
        self.assertTrue(flow.scroll.isVisible())
        self.assertEqual(set(flow.canvas.cards), {'environment', 'parallel', 'android'})
        self.assertEqual(set(flow.canvas.edges), {('environment', 'parallel'),
            ('parallel', 'android')})
        flow.canvas.cards['android'][0].click()
        prerequisites = self.panel.review_workspace.prerequisite_layout
        self.assertEqual({prerequisites.itemAt(i).widget().full_text for i in range(1, prerequisites.count())},
                         {'Check environment', 'Parallel'})
        cards.open_group('deliver.firebase')
        self.assertEqual(cards.pages.currentIndex(), 0)
        self.assertEqual(set(self.panel.review_workspace.rows), {'firebase'})
        self.assertEqual(self.panel.review_workspace.selected, 'firebase')
        self.assertTrue(flow.isHidden())
        self.assertEqual(self.panel.review_workspace.prerequisite_layout.itemAt(1).widget().full_text, 'Prepare')
        cards.open_group('source')
        self.assertTrue(flow.isHidden())
        self.assertIn('No executable source subtasks', self.panel.review_workspace.context_info.text())
        self.assertEqual(plan.data(), before)
        self.assertFalse((self.root / 'package.bin').exists())

    def test_connectors_have_horizontal_final_segment_centred_in_arrowhead(self):
        for y in (-400, 0, 400):
            for long_edge in (False, True):
                end = QPointF(300, y)
                path, arrow = dependency_path(QPointF(0, 0), end, long_edge=long_edge, gutter=600)
                before = path.elementAt(path.elementCount() - 2)
                self.assertEqual(before.y, end.y())
                self.assertLess(before.x, end.x() - 8)
                self.assertEqual(arrow[0], end)
                self.assertEqual((arrow[1].y() + arrow[2].y()) / 2, end.y())

    def test_proposed_overview_reflows_without_changing_graph_or_selection(self):
        from build_manager.proposed_workflow import ProposedStep, ProposedWorkflow
        from build_manager.workflow_ui import WorkflowFlow
        plan = ProposedWorkflow((
            ProposedStep('source', 'Source', 'Current files', section='source'),
            ProposedStep('test', 'Android', 'Required checks', ('source',)),
            ProposedStep('build', 'Build', 'Development package', ('test',), section='delivery'),
            ProposedStep('deliver', 'Deliver', 'Review before delivery', ('build',), section='delivery')))
        view = WorkflowFlow(graph_only=True)
        self.addCleanup(view.close)
        view.reset(plan)
        view.resize(760, 680)
        view.show()
        view.select('build')
        for _ in range(5):
            self.app.processEvents()
        cards = {key: value[0] for key, value in view.canvas.cards.items()}
        edges = list(view.canvas.edges)
        self.assertTrue(view.canvas.vertical)
        for source, target in edges:
            self.assertLess(cards[source].geometry().bottom(), cards[target].geometry().top())
        self.assertEqual(view.scroll.horizontalScrollBar().maximum(), 0)
        view.resize(1500, 500)
        for _ in range(5):
            self.app.processEvents()
        self.assertFalse(view.canvas.vertical)
        self.assertEqual(view.canvas.edges, edges)
        self.assertEqual(view.selected, 'build')
        self.assertIs(view.canvas.cards['build'][0], cards['build'])
        self.assertTrue(cards['build'].isChecked())
        for source, target in edges:
            self.assertLess(cards[source].geometry().right(), cards[target].geometry().left())

    def test_exact_map_orientation_and_fit_contain_the_entire_plan(self):
        from build_manager.workflow_ui import WorkflowFlow
        phases = tuple(Phase(f'step-{i}', (sys.executable, '-V'), str(self.root),
            dependencies=(f'step-{i-1}',) if i else ()) for i in range(8))
        plan = Plan('Fixture', 'Test', {}, phases, str(self.root))
        before = plan.data()
        view = WorkflowFlow(graph_only=True)
        self.addCleanup(view.close)
        view.reset(plan, preview=True)
        view.resize(700, 600)
        view.show()
        for orientation in ('horizontal', 'vertical', 'best'):
            view.orientation.setCurrentIndex(view.orientation.findData(orientation))
            for _ in range(4):
                self.app.processEvents()
            view.fit_button.click()
            self.app.processEvents()
            if orientation != 'best':
                self.assertEqual(view.canvas.vertical, orientation == 'vertical')
            self.assertEqual(view.scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(view.scroll.verticalScrollBar().maximum(), 0)
            for card, _, _ in view.canvas.cards.values():
                rect = view.scroll.mapFromScene(view.scroll.proxy.mapRectToScene(QRectF(card.geometry()))).boundingRect()
                self.assertTrue(view.scroll.viewport().rect().contains(rect), (orientation, rect))
        view.set_scope({'step-6', 'step-7'})
        self.assertEqual(view.scroll.orientation, 'best')
        self.assertEqual(plan.data(), before)
