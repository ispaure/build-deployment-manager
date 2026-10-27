"""Workspace adapters retain their contention message and directory policy."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager.locking import workspace_lock


class WorkspaceLockTests(unittest.TestCase):
    def test_contention_and_release(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'nested/workspace.lock'
            with workspace_lock(path):
                with self.assertRaisesRegex(RuntimeError, 'Another operation owns this workspace'):
                    with workspace_lock(path):
                        self.fail('must not acquire')
            with workspace_lock(path):
                self.assertTrue(path.exists())
