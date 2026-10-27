"""Background verification preserves exact artifact review and UI lifetime."""
import hashlib
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import time
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from build_manager import Phase, Plan
from build_manager.ui import ManagerPanel
from build_manager.workflows import verify_artifacts
from commonUtils.runtime.operations import OperationCancelled
import test_ui as fixtures


class ReviewTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ManagerUITests.setUpClass.__func__)
    setUp = fixtures.ManagerUITests.setUp

    def retained(self):
        folder = self.root / 'retained'
        folder.mkdir()
        artifact = self.root / 'original.bin'
        artifact.write_bytes(b'example artifact' * 100000)
        captured = folder / 'captured.bin'
        captured.write_bytes(artifact.read_bytes())
        effect = self.root / 'effect'
        import sys
        plan = Plan('Fixture', 'review', {'commit': 'fixed'}, (
            Phase('prepare', (sys.executable, '-c', 'pass'), str(self.root)),
            Phase('upload', (sys.executable, '-c', f'from pathlib import Path; Path({str(effect)!r}).touch()'),
                  str(self.root), dependencies=('prepare',), effect='upload')), str(self.root / 'workspace'))
        plan.save(folder / 'plan.json')
        report = dict(schema=1, status='awaiting_review', plan_identity=plan.identity, phases=[
            dict(id='prepare', status='passed', artifacts=[dict(path=str(captured), original_path=str(artifact),
                                                             sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())]),
            dict(id='upload', status='awaiting_review')])
        result = folder / 'result.json'
        result.write_text(json.dumps(report))
        return result, report, artifact, effect

    def wait_review(self, panel):
        deadline = time.monotonic() + 5
        while panel.reviewing:
            self.app.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)

    def test_gui_continuation_reviews_and_forwards_changed_engine_identity(self):
        from PySide6.QtWidgets import QMessageBox
        from build_manager.identity import runtime_identity, engine_review_identity
        result, report, _, effect = self.retained()
        report['engine'] = dict(api=0, manager={'commit': 'old'}, commonUtils={'commit': 'old'})
        result.write_text(json.dumps(report))
        expected = engine_review_identity(report['engine'], runtime_identity())
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        with patch('build_manager.ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes) as review, \
                patch.object(panel, 'confirm_continuation', return_value=('upload',)), \
                patch.object(panel.session, 'launch') as launch:
            panel.resume_workflow(result)
            self.wait_review(panel)
            review.assert_called_once()
            self.assertEqual(launch.call_args.kwargs['engine_review'], expected)
            self.assertTrue(launch.call_args.kwargs['resume'])
        self.assertFalse(effect.exists())

    def test_legacy_device_history_omits_default_approval_field_and_still_opens(self):
        from dataclasses import replace
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem
        result, report, _, effect = self.retained()
        plan = Plan.load(result.parent / 'plan.json')
        plan = replace(plan, phases=(*plan.phases[:-1], replace(plan.phases[-1], effect='deploy')))
        plan.save(result.parent / 'plan.json')
        self.assertNotIn('approval_required', plan.data()['phases'][-1])
        report['plan_identity'] = plan.identity
        result.write_text(json.dumps(report))
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, str(result))
        panel.open_history(item, in_tab=True)
        self.assertEqual(panel.result, result)
        self.assertIn('Viewing retained run:', panel.status.text())
        self.assertEqual(panel.run_view.plan.project, plan.project)
        self.assertTrue(panel.safe_plan(plan).phases[-1].approval_required)
        self.assertFalse(effect.exists())

    def test_unknown_device_history_can_review_only_independent_upload(self):
        from dataclasses import replace
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem
        import sys
        result, report, _, effect = self.retained()
        plan = Plan.load(result.parent / 'plan.json')
        device = Phase('device', (sys.executable, '-c', 'raise SystemExit(9)'),
                       str(self.root), effect='deploy')
        plan = replace(plan, phases=(*plan.phases, device))
        plan.save(result.parent / 'plan.json')
        report.update(status='unknown', plan_identity=plan.identity)
        report['phases'].append(dict(id='device', status='unknown', operation_id='uncertain-device'))
        result.write_text(json.dumps(report))
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole, str(result))
        panel.open_history(item, in_tab=True)
        self.assertTrue(panel.continue_run.isEnabled())
        self.assertEqual(panel.continue_run.text(), 'Continue independent steps…')
        with patch.object(panel, 'confirm_continuation', return_value=('upload',)), \
                patch.object(panel.session, 'launch') as launch:
            panel.resume_workflow(result)
            self.wait_review(panel)
            self.assertEqual([a.step for a in launch.call_args.kwargs['approvals']], ['upload'])
        self.assertFalse(effect.exists())
        self.assertEqual(json.loads(result.read_text())['phases'][-1]['operation_id'], 'uncertain-device')

    def test_hashing_uses_bounded_shared_streams_and_checks_both_copies(self):
        _, report, artifact, _ = self.retained()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole file allocation')):
            verify_artifacts(report['phases'][0])
            artifact.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                verify_artifacts(report['phases'][0])
            with self.assertRaises(OperationCancelled):
                verify_artifacts(report['phases'][0], cancelled=lambda: True)

    def test_background_verification_keeps_qt_responsive_and_discards_stale_selection(self):
        result, _, _, effect = self.retained()
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        entered, release = Event(), Event()
        from commonUtils.runtime.streams import file_sha256
        def blocked(path, **options):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test failed to release hashing')
            return file_sha256(path, **options)
        ticks = []
        with patch('build_manager.workflows.file_sha256', side_effect=blocked), \
                patch.object(panel, 'confirm_continuation') as confirm:
            panel.resume_workflow(result)
            self.assertTrue(entered.wait(2))
            QTimer.singleShot(0, lambda: ticks.append('responsive'))
            self.app.processEvents()
            self.assertEqual(ticks, ['responsive'])
            panel.invalidate()
            release.set()
            self.wait_review(panel)
            confirm.assert_not_called()
        self.assertFalse(effect.exists())
        self.assertIn('selection changed', panel.status.text())

    def test_cancelled_review_never_opens_approval(self):
        result, _, _, effect = self.retained()
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        with patch.object(panel, 'confirm_continuation') as confirm:
            panel.resume_workflow(result)
            panel.cancel_operation()
            self.wait_review(panel)
            confirm.assert_not_called()
        self.assertFalse(effect.exists())

    def test_changed_artifact_in_review_dialog_is_rejected_before_effect(self):
        result, _, artifact, effect = self.retained()
        panel = ManagerPanel(fixtures.OtherProject(self.root))
        self.addCleanup(panel.close)
        def accept(*_):
            artifact.write_bytes(b'changed during dialog')
            return True
        with patch.object(panel, 'confirm_continuation', side_effect=accept):
            panel.resume_workflow(result)
            self.wait_review(panel)
            deadline = time.monotonic() + 10
            while panel.cancel.isEnabled():
                self.app.processEvents()
                time.sleep(.005)
                self.assertLess(time.monotonic(), deadline)
        self.assertFalse(effect.exists())
        self.assertIn('missing or changed', panel.preview.toPlainText())
