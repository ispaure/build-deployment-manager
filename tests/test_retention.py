"""Retention safety: active work, pins and external links survive pruning."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager.retention import lease, prune


class RetentionTests(unittest.TestCase):
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
            (root / '0').symlink_to(outside, target_is_directory=True)
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
            link.symlink_to(builds, target_is_directory=True)
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
