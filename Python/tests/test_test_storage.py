import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest

from build_manager import Phase, Plan
from build_manager.locking import workspace_lock
from build_manager.test_storage import delete, inventory


class TestEvidenceCleanup(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.project = SimpleNamespace(root=self.root, results_directory=self.root / 'runs',
                                       descriptor={'test_evidence': ['legacy']})

    def run_folder(self, name, *, status='passed', holds=()):
        run = self.project.results_directory / name
        run.mkdir(parents=True)
        plan = Plan('Fixture', 'Check', {}, (Phase('check', (sys.executable, '-V'), str(run)),),
                    str(self.root / 'workspace'))
        plan.save(run / 'plan.json')
        (run / 'result.json').write_text(json.dumps(dict(schema=1, plan_identity=plan.identity,
            status=status, phases=[dict(id='check', status=status)], holds=list(holds))))
        for name in ('check.log', 'copy.apk', 'summary.json', 'junit.xml', 'receipt.json'):
            (run / name).write_text(name)
        return run

    def test_bulk_evidence_and_entire_run_are_separate_actions(self):
        run = self.run_folder('done')
        legacy = self.root / 'legacy'
        legacy.mkdir()
        loose = legacy / 'old.jsonl'
        loose.write_text('old output')
        os.utime(loose, (time.time() - 90000,) * 2)
        (legacy / 'handoff.json').write_text('keep')
        rows = inventory(self.project)
        self.assertEqual({row['name'] for row in rows}, {'done', 'old.jsonl'})
        self.assertFalse(delete(self.project, rows)['skipped'])
        self.assertFalse(loose.exists())
        self.assertFalse((run / 'copy.apk').exists())
        self.assertFalse((run / 'check.log').exists())
        for name in ('plan.json', 'result.json', 'summary.json', 'junit.xml', 'receipt.json'):
            self.assertTrue((run / name).is_file())
        self.assertFalse(delete(self.project, inventory(self.project), entire=True)['skipped'])
        self.assertEqual(inventory(self.project), [])
        self.assertTrue((legacy / 'handoff.json').is_file())

    def test_rechecks_locks_holds_and_reviewed_identity(self):
        run = self.run_folder('done')
        self.run_folder('held', holds=[str(self.root / 'workspace')])
        self.run_folder('unknown', status='unknown')
        rows = {row['name']: row for row in inventory(self.project)}
        self.assertTrue(rows['held']['protected'])
        self.assertTrue(rows['unknown']['protected'])
        with workspace_lock(run / 'supervisor.lock'):
            self.assertTrue(delete(self.project, [rows['done']], entire=True)['skipped'])
        report = run / 'result.json'
        report.write_text(report.read_text() + '\n')
        self.assertEqual(len(delete(self.project, list(rows.values()))['skipped']), 3)
        self.assertTrue((run / 'check.log').is_file())

    @unittest.skipUnless(os.name != 'nt', 'Symlink creation requires Windows privileges')
    def test_linked_evidence_is_excluded_and_replacements_are_refused(self):
        run = self.run_folder('done')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.log').write_text('keep')
        (run / 'linked').symlink_to(outside, target_is_directory=True)
        row, = inventory(self.project)
        self.assertFalse(delete(self.project, [row])['skipped'])
        self.assertTrue((outside / 'private.log').is_file())
        run.rename(run.with_name('moved'))
        run.symlink_to(outside, target_is_directory=True)
        self.assertTrue(delete(self.project, [row], entire=True)['skipped'])
        self.assertTrue((outside / 'private.log').is_file())

    def test_dialog_loads_evidence_and_only_enables_allowed_actions(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QMessageBox
        from build_manager.storage_ui import StorageDialog

        app = QApplication.instance() or QApplication([])
        run = self.run_folder('done')
        self.run_folder('unknown', status='unknown')
        dialog = StorageDialog(self.project)
        self.addCleanup(dialog.close)

        def finish_worker():
            deadline = time.monotonic() + 5
            while dialog.busy:
                app.processEvents()
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.005)

        finish_worker()
        self.assertEqual(dialog.evidence.topLevelItemCount(), 0)
        dialog.tabs.setCurrentIndex(dialog.evidence_tab)
        finish_worker()
        items = {dialog.evidence.topLevelItem(index).text(0): dialog.evidence.topLevelItem(index)
                 for index in range(dialog.evidence.topLevelItemCount())}
        items['unknown'].setSelected(True)
        self.assertFalse(dialog.evidence_files.isEnabled())
        self.assertFalse(dialog.evidence_runs.isEnabled())
        items['done'].setSelected(True)
        self.assertTrue(dialog.evidence_files.isEnabled())
        self.assertTrue(dialog.evidence_runs.isEnabled())
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, 'information'):
            dialog.evidence_files.click()
            finish_worker()
        self.assertFalse((run / 'check.log').exists())
        self.assertTrue((run / 'result.json').is_file())
