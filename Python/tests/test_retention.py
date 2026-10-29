from link_fixtures import directory_link
"""Retention safety: active work, pins and external links survive pruning."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager.retention import lease, prune, remove_tree


class RetentionTests(unittest.TestCase):
    def test_owned_scratch_with_readonly_git_objects_can_be_removed(self):
        import stat
        with TemporaryDirectory() as directory:
            root = Path(directory)/'scratch'; (root/'.git/objects').mkdir(parents=True)
            blob = root/'.git/objects/blob'; blob.write_bytes(b'owned fixture')
            blob.chmod(stat.S_IREAD)
            outside = Path(directory)/'retained'; outside.write_text('retained')
            remove_tree(root)
            self.assertFalse(root.exists())
            self.assertEqual(outside.read_text(), 'retained')

    def test_old_outputs_pruned_but_recent_pinned_active_and_links_survive(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'builds'
            root.mkdir()
            for number in range(1, 8):
                path = root / str(number)
                path.mkdir()
                (path / 'artifact').write_text('evidence')
                os.utime(path, (number, number))
            (root / '2/.keep').touch()
            os.utime(root / '2', (2, 2))
            outside = Path(directory).resolve() / 'outside'
            outside.mkdir()
            (outside / 'important').touch()
            directory_link(root / '0', outside)
            # lease refreshes age as well as holding a lock; force an old age
            # here to prove the lock itself prevents deletion.
            with lease(root / '3'):
                os.utime(root / '3', (3, 3))
                preview = prune(root, eligible=lambda p: p.name.isdigit(), now=100000, keep=2)
                self.assertEqual(set(map(lambda p: Path(p).name, preview)), {'1', '4', '5'})
                self.assertTrue((root / '1').exists())
                prune(root, eligible=lambda p: p.name.isdigit(), now=100000, keep=2, apply=True)
            self.assertEqual({p.name for p in root.iterdir() if p.is_dir()}, {'0', '2', '3', '6', '7'})
            self.assertTrue((outside / 'important').exists())

    def test_recent_and_symlinked_parent_are_never_swept(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builds = root / 'builds'
            builds.mkdir()
            for name in ('1', '2', '3', '4'):
                (builds / name).mkdir()
            self.assertEqual(prune(builds, eligible=lambda p: True, apply=True), [])
            link = root / 'linked'
            directory_link(link, builds)
            self.assertEqual(prune(link, eligible=lambda p: True, age_days=0, apply=True), [])
            self.assertEqual(len([p for p in builds.iterdir() if p.is_dir()]), 4)

    def test_failed_lease_releases_lock_and_refreshes_age(self):
        with TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'build'
            with self.assertRaises(ValueError), lease(path):
                raise ValueError('build failed')
            with lease(path):
                self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()

class ResourceLockTests(unittest.TestCase):
    def test_executor_cannot_start_against_a_leased_snapshot(self):
        from build_manager.executor import Executor
        from build_manager.locking import workspace_lock
        from build_manager.models import Phase, Plan
        import sys
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resource = root / 'source.lock'
            plan = Plan('fixture', 'test', {},
                        (Phase('test', (sys.executable, '-c', 'raise SystemExit(99)'), str(root)),),
                        str(root / 'workspace'), resource_locks=(str(resource),))
            with workspace_lock(resource):
                report = Executor().run(plan, root / 'results')
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['phases'], [])
            self.assertIn('owns this workspace', report['error'])


class WindowsReleaseWaitTests(unittest.TestCase):
    def test_transient_windows_handle_retries_but_other_failures_do_not(self):
        from unittest.mock import patch
        from build_manager.retention import remove_tree
        error = PermissionError('held executable')
        error.winerror = 32
        with patch('build_manager.retention.os.name', 'nt'), \
                patch('build_manager.retention._remove_tree_once', side_effect=[error, None]) as remove, \
                patch('build_manager.retention.time.sleep'):
            remove_tree('owned fixture')
            self.assertEqual(remove.call_count, 2)
        error.winerror = 13
        with patch('build_manager.retention.os.name', 'nt'), \
                patch('build_manager.retention._remove_tree_once', side_effect=error) as remove:
            with self.assertRaises(PermissionError):
                remove_tree('owned fixture')
            self.assertEqual(remove.call_count, 1)

    def test_persistent_windows_lock_remains_a_bounded_failure(self):
        from unittest.mock import patch
        from build_manager.retention import remove_tree
        error = PermissionError('persistent lock')
        error.winerror = 5
        with patch('build_manager.retention.os.name', 'nt'), \
                patch('build_manager.retention._remove_tree_once', side_effect=error) as remove, \
                patch('build_manager.retention.time.monotonic', side_effect=[0, 0, 4]), \
                patch('build_manager.retention.time.sleep'):
            with self.assertRaises(PermissionError):
                remove_tree('owned fixture')
            self.assertEqual(remove.call_count, 2)


class BudgetRetentionTests(unittest.TestCase):
    def test_pressure_evicts_oldest_recent_entries_but_keeps_pins_locks_and_newest(self):
        from unittest.mock import patch
        from build_manager.locking import workspace_lock
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for i in range(1, 8):
                path = root / str(i); path.mkdir()
                (path / 'data').write_bytes(b'x' * 100)
                os.utime(path, (1000 + i, 1000 + i))
            (root / '1/.keep').touch(); os.utime(root / '1', (1001, 1001))
            with workspace_lock(root / '.2.retention.lock'), patch('build_manager.retention.allocated_bytes', return_value=100):
                args = dict(eligible=lambda p: p.name.isdigit(), keep=2, now=1100,
                            age_days=7, max_bytes=400)
                preview = prune(root, **args)
                self.assertEqual([Path(p).name for p in preview], ['3', '4', '5'])
                self.assertEqual(prune(root, apply=True, **args), preview)
            self.assertTrue(all((root / str(i)).exists() for i in (1, 2, 6, 7)))

    def test_pressure_respects_grace_and_does_not_count_link_targets(self):
        from build_manager.retention import allocated_bytes
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); builds = root / 'builds'; builds.mkdir()
            outside = root / 'outside'; outside.mkdir(); (outside / 'data').write_bytes(b'x' * 8192)
            for i in range(4):
                path = builds / str(i); path.mkdir(); os.utime(path, (1000, 1000))
            directory_link(builds / '0/link', outside)
            self.assertEqual(allocated_bytes(builds / '0'), 0)
            self.assertEqual(prune(builds, eligible=lambda p: True, keep=1, now=1100,
                                   max_bytes=0, grace_days=1), [])


class AccessDateRetentionTests(unittest.TestCase):
    def test_last_used_overrides_old_directory_mtime_for_age_and_order(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for i in range(5):
                path = root / str(i); path.mkdir(); os.utime(path, (1, 1))
            # Entry zero has an old directory but was reused most recently.
            times = {'0': 100000, '1': 100001, '2': 100002, '3': 100003, '4': 1}
            rows = prune(root, eligible=lambda p: p.name.isdigit(), keep=2, now=100004,
                         last_used=lambda p: times[p.name])
            self.assertEqual([Path(p).name for p in rows], ['4'])
