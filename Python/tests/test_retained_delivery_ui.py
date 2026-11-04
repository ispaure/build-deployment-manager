"""Saved-input delivery prepares a reviewable new plan, never an automatic install."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QDialog
from build_manager.retained_delivery_ui import RetainedDeliveryDialog
from build_manager.ui import ManagerPanel
import test_retained_delivery as fixtures
from test_ui import OtherProject


class RetainedDeliveryUITests(unittest.TestCase):
    setUp = fixtures.RetainedDeliveryTests.setUp
    save = fixtures.RetainedDeliveryTests.save

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def project_for_ui(self):
        project = OtherProject(self.root)
        project.descriptor = dict(name='Fixture', project_id='fixture')
        project.journey_capability = dict(schema=1,
            platforms={'example': dict(operation='Test', backend='Local fixture')},
            destinations={'phones': dict(label='Saved phones', platforms=['example'])})
        project.run_fields = [dict(id='recipients', label='Recipients', kind='multiselect', default='[]',
                                  destinations=['phones'])]
        project.retained_delivery_plan = Mock(return_value=self.fresh)
        return project

    def test_dialog_requires_explicit_destination_and_recipients(self):
        dialog = RetainedDeliveryDialog(self.project_for_ui(), self.directory)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.prepare.isEnabled())
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.destinations['phones'].setChecked(True)
        dialog.accept()
        self.assertIn('recipient', dialog.message.text().lower())
        dialog.fields.controls['recipients'].setText('["saved-phone"]')
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.choices(), dict(destinations=['phones'], run_overrides={'recipients': '["saved-phone"]'}))

    def test_async_preparation_reviews_old_source_and_never_starts_delivery(self):
        project = self.project_for_ui()
        panel = ManagerPanel(project); self.addCleanup(panel.close)
        panel.result = self.directory / 'result.json'
        before = panel.result.read_bytes()
        def choose(dialog):
            dialog.destinations['phones'].setChecked(True)
            dialog.fields.controls['recipients'].setText('["new-phone"]')
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(RetainedDeliveryDialog, 'exec', new=choose), patch.object(panel, 'run_plan') as start:
            panel.request_retained_delivery()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005)
                self.assertLess(time.monotonic(), deadline)
            start.assert_not_called()
        project.retained_delivery_plan.assert_called_once_with(run_directory=str(self.directory),
            destinations=['phones'], run_overrides={'recipients': '["new-phone"]'})
        self.assertEqual(panel.plan.source, self.previous.source)
        self.assertEqual(panel.stages.currentIndex(), 1)
        self.assertEqual(panel.start.text(), 'Start reviewed workflow')
        self.assertEqual((self.directory / 'result.json').read_bytes(), before)
        self.assertFalse(Path(self.fresh.workspace).exists())

    def test_unsupported_projects_do_not_offer_the_action(self):
        panel = ManagerPanel(OtherProject(self.root)); self.addCleanup(panel.close)
        self.assertTrue(panel.retained_delivery.isHidden())
