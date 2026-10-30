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

    def test_operation_lock_survives_workspace_removal_and_blocks_recreation(self):
        from build_manager.locking import operation_lock_path
        from build_manager.retention import remove_tree
        with TemporaryDirectory() as folder:
            workspace = Path(folder) / 'disposable'
            workspace.mkdir()
            logical = workspace / 'operation.lock'
            with workspace_lock(logical):
                self.assertFalse(logical.exists())
                self.assertTrue(operation_lock_path(workspace).exists())
                remove_tree(workspace)
                self.assertFalse(workspace.exists())
                with self.assertRaises(RuntimeError):
                    with workspace_lock(logical):
                        self.fail('removal must not bypass operation ownership')
                self.assertFalse(workspace.exists())
            with workspace_lock(logical):
                self.assertFalse(workspace.exists())
