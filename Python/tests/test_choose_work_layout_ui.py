"""Choose-work proportions and review dependency maps remain usable and read-only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication
from build_manager import Phase
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
        self.assertEqual(set(flow.canvas.cards), {'firebase', 'prepare', 'android', 'ios', 'environment', 'parallel'})
        self.assertIn(('prepare', 'firebase'), flow.canvas.edges)
        self.assertIn('from other cards', self.panel.review_workspace.task_heading.text())
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
