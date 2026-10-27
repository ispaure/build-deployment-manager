"""Activity navigation and stopping are distinct from completed outcomes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PySide6.QtWidgets import QApplication
from build_manager.run_ui import RunView
from test_journeys import integrated


class RunningStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.view = RunView()
        self.addCleanup(self.view.close)
        self.view.reset(integrated(Path(root.name)))

    def test_running_and_capacity_buttons_inspect_actual_steps(self):
        self.view.update_phase(dict(id='android', status='running'))
        self.view.update_phase(dict(id='ios', status='waiting_resource', reason='Worker occupied'))
        self.assertEqual(self.view.activity_buttons['running'].text(), 'Running · 1')
        self.assertEqual(self.view.activity_buttons['waiting_resource'].text(), 'Waiting for capacity · 1')
        self.view.activity_buttons['waiting_resource'].click()
        self.assertEqual(self.view.selected, 'ios')
        self.assertIn('Worker occupied', self.view.detail.toPlainText())

    def test_cancelling_never_fakes_a_cancelled_or_successful_result(self):
        self.view.update_phase(dict(id='android', status='running'))
        self.view.cancellation_requested()
        self.assertIn('Stopping…', self.view.summary.text())
        self.assertEqual(self.view.facts['android']['status'], 'running')
        self.assertEqual(self.view.outcome, '')
        self.assertFalse(self.view.activity_buttons['running'].isEnabled())
        self.view.complete(dict(status='cancelled'))
        self.assertFalse(self.view.cancelling)
        self.assertTrue(self.view.activity.isHidden())
        self.assertIn('cancelled', self.view.summary.text())

    def test_reconnection_wait_is_visible_without_marking_a_failed_deployment(self):
        self.view.update_phase(dict(id='android', status='retrying', retry_count=2,
                                    reason='Selected device is offline'))
        self.assertEqual(self.view.activity_buttons['retrying'].text(), 'Waiting to reconnect · 1')
        self.view.activity_buttons['retrying'].click()
        self.assertEqual(self.view.selected, 'android')
        self.assertIn('Other work continues', self.view.next_action.text())
        self.assertEqual(self.view.outcome, '')

    def test_approval_remains_visible_after_the_process_has_paused(self):
        self.view.update_phase(dict(id='firebase', status='awaiting_review'))
        self.view.complete(dict(status='awaiting_review'))
        self.assertTrue(self.view.activity.isHidden())
        self.assertFalse(self.view.attention_review.isHidden())
        self.assertFalse(self.view.attention_review.isEnabled())
