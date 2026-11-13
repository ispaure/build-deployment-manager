"""Prepared review yields between batches and exposes every exact task."""
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from build_manager import Phase, Plan
from build_manager.review_presentation import prepare_review_data
from build_manager.review_ui import ReviewPlanView
from build_manager.workflow_cards_ui import FlowCanvas


class ReviewPreparationResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ReviewPlanView()
        self.addCleanup(self.view.close)
        self.view.resize(1150, 800)
        self.view.show()
        self.app.processEvents()

    def plan(self, count, *, prefix='check', source=None):
        phases = tuple(Phase(f'{prefix}.{i:03}', (sys.executable, '-V'), str(Path.cwd()),
                             dependencies=(f'{prefix}.{i - 1:03}',) if i % 10 else ())
                       for i in range(count))
        return Plan('Fixture', 'Check', source or {'commit': 'captured'}, phases, str(Path.cwd()))

    def wait(self, predicate):
        deadline = monotonic() + 5
        while not predicate():
            self.app.processEvents()
            self.assertLess(monotonic(), deadline)
            sleep(.001)

    def test_large_reset_yields_before_every_row_is_ready_and_defers_hidden_evidence(self):
        plan = self.plan(500, source={'commit': 'captured', 'note': 'password=hidden-value'})
        original = plan.data()
        prepared = prepare_review_data(plan)
        materialized = []
        initial_reset = FlowCanvas.reset

        def capture(canvas, data, *args, **kwargs):
            materialized.append(len(data.phases))
            return initial_reset(canvas, data, *args, **kwargs)

        observed = []
        self.view.rendering_finished.connect(lambda: observed.append(('ready', len(self.view.rows))))
        with patch.object(FlowCanvas, 'reset', capture):
            self.view.reset(prepared.plan, prepared=prepared)
            self.assertTrue(self.view.rendering)
            self.assertFalse(self.view.tasks.isEnabled())
            self.assertFalse(self.view.flow.isEnabled())
            self.assertEqual(self.view.plan_data.document().characterCount(), 1)
            QTimer.singleShot(0, lambda: observed.append(('input', len(self.view.rows))))
            self.wait(lambda: not self.view.rendering)
            self.assertTrue(self.view.flow.isEnabled())
            self.assertEqual(materialized, [2])
            self.view.flow.open_group('operation')
            self.wait(lambda: not self.view.rendering)
            self.assertEqual(materialized, [2])
        self.assertEqual(observed[0][0], 'input')
        self.assertLess(observed[0][1], len(plan.phases))
        self.assertEqual(observed[1], ('ready', len(plan.phases)))
        self.assertEqual(self.view.board.topLevelItemCount(), len(plan.phases))
        self.assertEqual(tuple(self.view.rows), tuple(phase.id for phase in plan.phases))
        self.assertEqual(self.view.flow.pages.currentIndex(), 0)
        self.assertFalse(self.view.flow.nested_navigation)
        self.view.inspect_phase('check.499')
        self.assertIn('check.499', self.view.command.toPlainText())
        self.assertEqual(self.view.plan_data.document().characterCount(), 1)
        self.view.plan_tabs.setCurrentWidget(self.view.plan_data)
        data = json.loads(self.view.plan_data.toPlainText())
        self.assertEqual(len(data['phases']), 500)
        self.assertEqual(data['source']['note'], 'password=[redacted]')
        self.assertEqual(plan.data(), original)

    def test_cancelled_render_cannot_append_to_replacement(self):
        first = prepare_review_data(self.plan(200))
        second = prepare_review_data(self.plan(3, prefix='replacement'))
        finishes = []
        self.view.rendering_finished.connect(lambda: finishes.append(True))
        self.view.reset(first.plan, prepared=first)
        self.view.inspect_phase('check.199')
        self.assertTrue(self.view.rendering)
        self.view.cancel_rendering()
        self.view.reset(second.plan, prepared=second)
        self.app.processEvents()
        self.assertEqual(finishes, [])
        self.assertEqual(tuple(self.view.rows), ('replacement.000', 'replacement.001', 'replacement.002'))
        self.assertEqual(self.view.board.topLevelItemCount(), 3)
        self.assertEqual(self.view.selected, '')

    def test_enclosing_view_can_stage_worker_data_for_one_reset(self):
        prepared = prepare_review_data(self.plan(100))
        self.view.stage_prepared(prepared)
        with patch('build_manager.review_ui.review_data', side_effect=AssertionError('used GUI fallback')):
            self.view.reset(prepared.plan, preview=False)
            self.wait(lambda: not self.view.rendering)
        self.assertEqual(len(self.view.rows), 100)
        self.view.reset(prepared.plan, preview=False)
        self.assertTrue(self.view.rendering)
        self.wait(lambda: not self.view.rendering)
        self.assertEqual(len(self.view.rows), 100)

    def test_worker_presentation_has_no_qt_imports(self):
        code = ("import sys; from build_manager.review_presentation import prepare_review_data; "
                "assert not any(name.startswith(('PySide6', 'PyQt')) for name in sys.modules)")
        process = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True,
                                 text=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
