"""Windows evidence ZIPs retain directory structure on a non-Windows host."""
import base64
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import zipfile

from build_manager.windows_guest import WindowsGuest


class WindowsEvidenceTests(unittest.TestCase):
    def test_cleanup_retries_only_the_known_transient_and_remains_bounded(self):
        guest = WindowsGuest(Mock(), 'vm', 'workspace', 'token', 'operation')
        transient = RuntimeError('Windows guest command failed (255): PrlJob_GetRetCode: Invalid argument')
        with patch.object(guest, 'call', side_effect=[transient, None]) as call, patch('build_manager.windows_guest.time.sleep'):
            guest.remove_paths(['reports-operation'])
            self.assertEqual(call.call_count, 2)
            self.assertEqual(call.call_args_list[0], call.call_args_list[1])
        with patch.object(guest, 'call', side_effect=transient) as call, patch('build_manager.windows_guest.time.sleep'):
            with self.assertRaises(RuntimeError): guest.remove_paths(['reports-operation'])
            self.assertEqual(call.call_count, 3)
        with patch.object(guest, 'call', side_effect=RuntimeError('Workspace ownership mismatch')) as call:
            with self.assertRaisesRegex(RuntimeError, 'ownership'): guest.remove_paths(['reports-operation'])
            self.assertEqual(call.call_count, 1)

    def fixture(self, name):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            directory = zipfile.ZipInfo('reports\\parity\\before\\Python\\')
            directory.external_attr = 0x10
            archive.writestr(directory, b'')
            archive.writestr(name, b'{"verified":true}')
        payload = stream.getvalue()
        client = Mock()
        client.powershell.return_value = json.dumps(dict(data=base64.b64encode(payload).decode(), sha256=hashlib.sha256(payload).hexdigest())).encode()
        return WindowsGuest(client, 'fixture-vm', 'fixture-workspace', 'fixture-token', 'fixture-operation')

    def test_backslash_directory_entries_are_directories_after_transport(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence'
            self.fixture('reports\\parity\\before\\Python\\result.json').collect(['reports'], target)
            self.assertEqual(json.loads((target / 'reports/parity/before/Python/result.json').read_text()), {'verified': True})

    def test_archive_cannot_escape_result_directory(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence'
            with self.assertRaisesRegex(ValueError, 'escapes'):
                self.fixture('..\\escape.json').collect(['reports'], target)
            self.assertFalse((Path(directory) / 'escape.json').exists())
