"""Interrupted cleanup and concurrent controllers preserve ownership and run state."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan, retention
from build_manager.executor import Executor
from build_manager.locking import workspace_lock


class StorageInterruptionTests(unittest.TestCase):
    def test_bulk_failure_keeps_ownership_and_original_age_for_retry(self):
        for failure in (PermissionError('fixture busy'), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), TemporaryDirectory() as directory:
                parent = Path(directory).resolve(); root = parent / 'cache'; root.mkdir()
                marker = root / 'info.plist'; marker.write_bytes(b'ownership proof')
                (root / 'bulk').mkdir(); (root / 'bulk/data').write_bytes(b'rebuildable')
                os.utime(root, (1000, 1000))
                remove = retention._remove_tree_once
                def interrupted(path):
                    if Path(path).name == 'bulk':
                        raise failure
                    return remove(path)
                with patch.object(retention, '_remove_tree_once', interrupted):
                    with self.assertRaises(type(failure)):
                        retention.remove_tree(root, ownership_files=('info.plist',))
                self.assertEqual(marker.read_bytes(), b'ownership proof')
                self.assertEqual(root.stat().st_mtime, 1000)
                result = retention.delete_owned(parent, ['cache'], eligible=lambda p: (p / 'info.plist').is_file(),
                                                ownership_files=('info.plist',))
                self.assertEqual(result['removed'], [str(root)])
                self.assertFalse(root.exists())

    def test_hard_stop_during_bulk_removal_keeps_marker(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'cache'; root.mkdir()
            (root / 'info.plist').write_bytes(b'ownership proof')
            (root / 'bulk').mkdir()
            source = Path(__file__).resolve().parents[1]
            code = '''import os, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from build_manager import retention
original = retention._remove_tree_once
def stop(path):
    if Path(path).name == 'bulk': os._exit(75)
    return original(path)
retention._remove_tree_once = stop
retention.remove_tree(Path(sys.argv[2]), ownership_files=('info.plist',))
'''
            result = subprocess.run([sys.executable, '-I', '-c', code, str(source), str(root)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 75, result.stderr)
            self.assertEqual((root / 'info.plist').read_bytes(), b'ownership proof')
            retention.remove_tree(root, ownership_files=('info.plist',))

    def test_invalid_hold_expiry_does_not_remove_protection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); path = root / 'cache'; path.mkdir()
            record = root / '.cache.manager-holds.json'
            for expiry in (float('nan'), float('inf'), True, -1, 'tomorrow'):
                record.write_text(json.dumps(dict(schema=1, values=dict(leases={'owner': expiry}))))
                self.assertIn('Unreadable', retention.protection_reason(path))
            record.unlink()
            record.symlink_to(root / 'missing')
            self.assertIn('Unreadable', retention.protection_reason(path))


class ControllerAdmissionTests(unittest.TestCase):
    def fixture(self, root):
        output = root / 'run'; output.mkdir()
        plan = Plan('Fixture', 'Check', {}, (Phase('check', (sys.executable, '-c', 'pass'), str(root)),), str(root / 'workspace'))
        plan.save(output / 'plan.json')
        report = dict(schema=1, status='failed', plan_identity=plan.identity, seconds=0,
                      phases=[dict(id='check', status='failed', required=True)])
        (output / 'result.json').write_text(json.dumps(report))
        return plan, output, report

    def test_rejected_controller_does_not_overwrite_active_report(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); plan, output, _ = self.fixture(root)
            before = (output / 'result.json').read_bytes()
            with workspace_lock(output / 'supervisor.lock'), self.assertRaisesRegex(RuntimeError, 'owns'):
                Executor().run(plan, output, resume=True)
            self.assertEqual((output / 'result.json').read_bytes(), before)

    def test_controller_reads_latest_report_only_after_admission(self):
        import build_manager.executor as module
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); plan, output, report = self.fixture(root)
            real_lock = workspace_lock
            @contextmanager
            def lock(path):
                with real_lock(path):
                    if Path(path).name == 'supervisor.lock':
                        # Another controller completed after this request was
                        # made but before it acquired the supervisor lock.
                        report.update(status='passed', phases=[dict(id='check', status='passed', required=True)])
                        (output / 'result.json').write_text(json.dumps(report))
                    yield
            with patch.object(module, 'workspace_lock', lock), patch.object(Executor, 'run_phase') as phase:
                result = Executor().run(plan, output, resume=True)
            self.assertEqual(result['status'], 'passed')
            phase.assert_not_called()

    def test_missing_resume_does_not_create_a_run_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); plan, _, _ = self.fixture(root)
            missing = root / 'missing'
            with self.assertRaisesRegex(ValueError, 'missing'):
                Executor().run(plan, missing, resume=True)
            self.assertFalse(missing.exists())
