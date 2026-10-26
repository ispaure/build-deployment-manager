"""Delivery summaries preserve partial outcomes and lead to retained evidence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PySide6.QtWidgets import QApplication
from build_manager.run_ui import RunView
from test_journeys import integrated


class ResultsOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.plan = integrated(Path(root.name))
        self.view = RunView()
        self.addCleanup(self.view.close)
        self.view.reset(self.plan)

    def test_partial_delivery_is_explicit_and_inspectable(self):
        self.view.update_phase(dict(id='firebase', status='passed'))
        self.view.update_phase(dict(id='testflight', status='unknown'))
        self.view.complete(dict(status='unknown'))
        first, second = [self.view.delivered.topLevelItem(i) for i in range(2)]
        self.assertEqual(first.text(1), 'Delivered')
        self.assertEqual(second.text(1), 'Unknown outcome')
        self.view.inspect_delivered(second)
        self.assertEqual(self.view.selected, 'testflight')
        self.assertEqual(self.view.tabs.currentWidget(), self.view.steps.parentWidget())

    def test_success_opens_outputs_without_stealing_an_inspected_step(self):
        self.view.complete(dict(status='passed'))
        self.assertEqual(self.view.pages.currentWidget(), self.view.delivery_page)
        self.view.inspect_summary_phase('android')
        self.view.complete(dict(status='passed'))
        self.assertEqual(self.view.pages.currentIndex(), 1)

    def test_prepared_files_keep_path_and_full_identity_in_evidence(self):
        self.view.update_phase(dict(id='prepare', status='passed', artifacts=[dict(
            path='/retained/App.zip', sha256='a'*64)]))
        item = self.view.delivered.topLevelItem(2)
        self.assertEqual(item.text(0), 'App.zip')
        self.assertEqual(item.text(2), '/retained/App.zip')
        self.view.inspect_delivered(item)
        self.assertIn('a'*64, self.view.detail.toPlainText())
