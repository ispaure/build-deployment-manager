"""Regression coverage for storage ownership changes and diagnostic visibility."""
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from link_fixtures import directory_link
from build_manager import retention


class StorageReviewTests(unittest.TestCase):
    def test_manual_delete_rechecks_ownership_after_acquiring_entry_lock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); output = root / 'candidate'; output.mkdir()
            marker = output / 'owned'; marker.touch()
            real_lock = retention.workspace_lock
            @contextmanager
            def lock(path):
                with real_lock(path):
                    if Path(path).name == '.candidate.retention.lock':
                        marker.unlink()
                    yield
            with patch.object(retention, 'workspace_lock', lock):
                result = retention.delete_owned(root, ['candidate'], eligible=lambda p: (p / 'owned').exists())
            self.assertEqual(result['removed'], [])
            self.assertTrue(output.is_dir())
            self.assertIn('no longer', result['skipped'][0])

    def test_manual_delete_does_not_follow_root_redirected_during_admission(self):
        with TemporaryDirectory() as directory:
            parent = Path(directory).resolve(); root = parent / 'builds'; root.mkdir()
            (root / 'candidate').mkdir()
            foreign = parent / 'foreign'; (foreign / 'candidate').mkdir(parents=True)
            (foreign / 'candidate/private').write_text('preserve')
            real_lock = retention.workspace_lock
            @contextmanager
            def lock(path):
                # Windows' live lock handles prevent renaming the root at all.
                # Simulate admission without those handles to exercise the
                # subsequent ownership recheck on both native link types.
                with (nullcontext() if os.name == 'nt' else real_lock(path)):
                    if Path(path).name == '.candidate.retention.lock':
                        root.rename(parent / 'original')
                        directory_link(root, foreign)
                    yield
            with patch.object(retention, 'workspace_lock', lock):
                result = retention.delete_owned(root, ['candidate'], eligible=lambda p: True)
            self.assertEqual(result['removed'], [])
            self.assertEqual((foreign / 'candidate/private').read_text(), 'preserve')
            self.assertTrue((parent / 'original/candidate').is_dir())

    def test_unreadable_pin_or_invalid_hold_state_stays_protected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'output'; path.mkdir()
            with patch.object(retention.os, 'walk', side_effect=PermissionError('fixture unreadable')):
                self.assertEqual(retention.protection_reason(path), 'Unreadable pin state; protected')
            (path.parent / '.output.manager-holds.json').write_text(json.dumps(dict(schema=1, values=dict(leases=[]))))
            self.assertEqual(retention.protection_reason(path), 'Unreadable workflow hold; protected')

    def test_nested_holds_protect_explicitly_owned_enclosing_tree(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); output = root / 'checkout'; (output / 'work').mkdir(parents=True)
            retention.set_workflow_hold(output / 'work', 'unknown-outcome')
            args = dict(eligible=lambda p: p.name == 'checkout', protection=retention.nested_workflow_hold_reason)
            rows = retention.owned_entries(root, **args)
            self.assertIn('retained workflow', rows[0]['protected'])
            self.assertEqual(retention.prune(root, keep=0, age_days=0, apply=True, **args), [])
            self.assertEqual(retention.delete_owned(root, ['checkout'], **args)['removed'], [])
            self.assertTrue((output / 'work').exists())

    def test_cache_budget_counts_protected_allocations(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); specs = []
            for i in range(3):
                path = root / str(i) / 'cache'; path.mkdir(parents=True)
                os.utime(path, (1000 + i, 1000 + i))
                specs.append(dict(root=path.parent, eligible=lambda p: p.name == 'cache'))
            (root / '0/cache/.keep').touch()
            with patch.object(retention, 'allocated_bytes', return_value=100):
                rows = retention.prune_cache_groups(specs, age_days=7, max_bytes=200, now=10000)
            self.assertEqual(rows, [str(root / '1/cache')])

    def test_failed_maintenance_is_visible_without_rewriting_workload_status(self):
        from build_manager.api import read_status, read_storage_maintenance
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            report = root / 'result.json'
            report.write_text(json.dumps(dict(schema=1, status='passed', phases=[])))
            before = report.read_bytes()
            maintenance = root / 'storage-maintenance.json'
            maintenance.write_text(json.dumps(dict(status='incomplete', warnings=['Xcode inventory unavailable'])))
            result = read_status(root)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['storage_maintenance']['status'], 'incomplete')
            self.assertEqual(report.read_bytes(), before)
            maintenance.write_bytes(b'x' * 262145)
            self.assertEqual(read_storage_maintenance(root)['status'], 'failed')

    def test_workflow_labels_support_windows_and_posix_paths(self):
        from build_manager.storage_ui import saved_run_name
        self.assertEqual(saved_run_name(r'C:\builds\runs\old\result.json'), 'old')
        self.assertEqual(saved_run_name('/builds/runs/old/result.json'), 'old')

    def test_retirement_rechecks_record_links_after_acquiring_supervisor(self):
        import sys
        from build_manager import Phase, Plan
        from build_manager import run_retirement
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); output = root / 'runs/old'; output.mkdir(parents=True)
            plan = Plan('Fixture', 'Check', {}, (Phase('check', (sys.executable, '-V'), str(root)),), str(root / 'workspace'))
            plan.save(output / 'plan.json')
            result = output / 'result.json'
            result.write_text(json.dumps(dict(schema=1, status='unknown', plan_identity=plan.identity, phases=[])))
            foreign = root / 'foreign.json'; foreign.write_bytes(result.read_bytes())
            real_lock = run_retirement.workspace_lock
            @contextmanager
            def lock(path):
                with real_lock(path):
                    if Path(path).name == 'supervisor.lock':
                        result.unlink()
                        result.symlink_to(foreign)
                    yield
            with patch.object(run_retirement, 'workspace_lock', lock), self.assertRaisesRegex(ValueError, 'ownership changed'):
                run_retirement.retire_run(root / 'runs', 'old', confirmed=True)
            self.assertNotIn('retirement', json.loads(foreign.read_text()))
