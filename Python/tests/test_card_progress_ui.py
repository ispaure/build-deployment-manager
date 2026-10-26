"""Card outcomes and progress reflect execution evidence, including dependencies."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication, QProgressBar
from build_manager import Phase, Plan
from build_manager.grouped_workflow_ui import GroupedFlowView
from build_manager.workflow_ui import FlowCanvas


class CardProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == '__main__':
    unittest.main()
