"""Windows evidence ZIPs retain directory structure on a non-Windows host."""
import base64
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
import zipfile

from build_manager.windows_guest import WindowsGuest


class WindowsEvidenceTests(unittest.TestCase):
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
