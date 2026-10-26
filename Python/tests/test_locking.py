"""Windows lock acquisition must not touch another process's byte range."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from build_manager import locking


class WindowsLockTests(unittest.TestCase):
    def test_initialization_cannot_write_into_another_process_lock(self):
        stream = MagicMock()
        stream.write.side_effect = PermissionError('fixture: byte already locked')
        stream.flush.side_effect = PermissionError('fixture: byte already locked')
        path = MagicMock()
        path.open.return_value.__enter__.return_value = stream
        api = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2,
                              locking=Mock(side_effect=[OSError('busy'), None, None]))
        with patch.object(locking, 'Path', return_value=path), \
                patch.object(locking, 'os', SimpleNamespace(name='nt')), \
                patch.object(locking.time, 'sleep'), \
                patch.dict('sys.modules', msvcrt=api):
            with locking.workspace_lock('fixture', timeout=1):
                self.assertEqual(api.locking.call_count, 2)
        self.assertEqual(api.locking.call_count, 3)
        stream.write.assert_not_called()
        stream.flush.assert_not_called()
        self.assertEqual(api.locking.call_args.args[1:], (api.LK_UNLCK, 1))
