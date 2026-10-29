"""Windows evidence ZIPs retain directory structure on a non-Windows host."""
import base64
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from threading import Event
import zipfile

from build_manager.windows_guest import WindowsGuest


class WindowsEvidenceTests(unittest.TestCase):
    def test_waiting_heartbeat_keeps_exact_completion_and_adds_no_guest_calls(self):
        from build_manager.parallels import Parallels
        guest = WindowsGuest(Parallels('/fixture/prlctl'), '00000000-0000-0000-0000-000000000001',
                             'workspace', 'token', 'operation')
        receipt = json.dumps(dict(exit=7, token='token', operation='operation', invocation='current')).encode()
        import subprocess
        process = Mock(returncode=0)
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', .2), (receipt, b'')]
        process.poll.return_value = 0
        rows = []
        with patch('build_manager.windows_guest.uuid4', return_value=Mock(hex='current')), \
             patch('build_manager.windows_guest.subprocess.Popen', return_value=process), \
             patch('build_manager.windows_guest.time.monotonic', side_effect=[0, 0, 31, 31]), \
             patch.object(guest, 'call') as transport:
            self.assertEqual(guest.run('python', ['fixture'], 'source', 'reports', {}, Event(),
                                      timeout=100, progress=rows.append), 7)
        transport.assert_not_called()
        self.assertEqual(rows, [dict(state='waiting', seconds=0), dict(state='waiting', seconds=31)])

    def test_lost_job_handle_recovers_exit_without_replaying_guest_work(self):
        from build_manager.parallels import Parallels
        guest = WindowsGuest(Parallels('/fixture/prlctl'), '00000000-0000-0000-0000-000000000001',
                             'workspace', 'token', 'operation')
        for code in (0, 7):
            process = Mock(returncode=255)
            process.communicate.return_value = (b'', b'PrlJob_GetRetCode: Invalid argument')
            process.poll.return_value = 255
            receipt = json.dumps(dict(exit=code, token='token', operation='operation', invocation='current')).encode()
            with patch('build_manager.windows_guest.uuid4', return_value=Mock(hex='current')), patch('build_manager.windows_guest.subprocess.Popen', return_value=process) as spawn, patch.object(guest, 'call', return_value=receipt) as read:
                self.assertEqual(guest.run('python', ['fixture'], 'source', 'reports', {}, Event(), timeout=10), code)
                self.assertEqual(spawn.call_count, 1)
                self.assertEqual(read.call_count, 1)

    def test_lost_request_before_admission_retries_the_same_invocation(self):
        from build_manager.parallels import Parallels
        guest = WindowsGuest(Parallels('/fixture/prlctl'), '00000000-0000-0000-0000-000000000001',
                             'workspace', 'token', 'operation')
        lost = Mock(returncode=255)
        lost.communicate.return_value = (b'', b'PrlJob_GetRetCode: Invalid argument')
        lost.poll.return_value = 255
        success = Mock(returncode=0)
        success.communicate.return_value = (json.dumps(dict(exit=0, token='token',
            operation='operation', invocation='current')).encode(), b'')
        success.poll.return_value = 0
        with patch('build_manager.windows_guest.uuid4', return_value=Mock(hex='current')), \
             patch('build_manager.windows_guest.subprocess.Popen', side_effect=[lost, success]) as spawn, \
             patch.object(guest, 'recover_completion', return_value=None), patch.object(guest, 'call') as write:
            self.assertEqual(guest.run('python', ['fixture'], 'source', 'reports', {}, Event(), timeout=10), 0)
        self.assertEqual(spawn.call_count, 2)
        first = json.loads(lost.communicate.call_args.kwargs['input'])
        second = json.loads(success.communicate.call_args.kwargs['input'])
        self.assertEqual(first, second)
        self.assertEqual(first['values']['invocation'], 'current')
        write.assert_not_called()  # Do not fence the request before its safe retry.

    def test_duplicate_admission_waits_for_verified_worker_exit(self):
        guest = WindowsGuest(Mock(), 'vm', 'workspace', 'token', 'operation')
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(dict(state='admitted', token='token',
            operation='operation', invocation='current')).encode(), b'')
        process.poll.return_value = 0
        with patch('build_manager.windows_guest.uuid4', return_value=Mock(hex='current')), \
             patch('build_manager.windows_guest.subprocess.Popen', return_value=process) as spawn, \
             patch.object(guest, 'recover_completion', return_value=7) as recover:
            self.assertEqual(guest.run('python', ['fixture'], 'source', 'reports', {}, Event(), timeout=10), 7)
        self.assertEqual(spawn.call_count, 1)
        recover.assert_called_once()

    def test_missing_or_stale_completion_never_implies_success(self):
        from build_manager.parallels import Parallels
        guest = WindowsGuest(Parallels('/fixture/prlctl'), '00000000-0000-0000-0000-000000000001',
                             'workspace', 'token', 'operation')
        process = Mock(returncode=255)
        process.communicate.return_value = (b'', b'PrlJob_GetRetCode: Invalid argument')
        process.poll.return_value = 255
        with patch('build_manager.windows_guest.subprocess.Popen', return_value=process), patch.object(guest, 'call', return_value=b''), patch.object(guest, 'recover_completion', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'transport failed'):
                guest.run('python', ['fixture'], 'source', 'reports', {}, Event(), timeout=10)
        for patch_record in (dict(token='other'), dict(operation='other'), dict(invocation='old'), dict(exit=True)):
            record = dict(exit=0, token='token', operation='operation', invocation='current')
            record.update(patch_record)
            with self.assertRaises(ValueError): guest.completion_code(record, 'current')

    def test_accepted_worker_can_finish_after_transport_disconnect(self):
        import time
        guest = WindowsGuest(Mock(), 'vm', 'workspace', 'token', 'operation')
        identity = dict(token='token', operation='operation', invocation='current')
        records = [json.dumps(dict(identity, state='running')).encode(),
                   json.dumps(dict(identity, exit=7)).encode()]
        with patch.object(guest, 'call', side_effect=records) as read:
            self.assertEqual(guest.recover_completion('reports', 'current', time.monotonic(), 10, Event()), 7)
            self.assertEqual(read.call_count, 2)

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

    def test_evidence_collection_retries_lost_result_handle_without_replaying_work(self):
        guest = self.fixture('reports/result.json')
        value = guest.client.powershell.return_value
        guest.client.powershell.side_effect = [RuntimeError('Windows guest command failed (255): PrlJob_GetResult: Invalid argument'), value]
        with TemporaryDirectory() as directory, patch('build_manager.windows_guest.time.sleep'):
            guest.collect(['reports'], Path(directory)/'evidence')
            self.assertEqual(guest.client.powershell.call_count, 2)
            self.assertEqual(json.loads((Path(directory)/'evidence/reports/result.json').read_text()), {'verified': True})

    def test_archive_cannot_escape_result_directory(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence'
            with self.assertRaisesRegex(ValueError, 'escapes'):
                self.fixture('..\\escape.json').collect(['reports'], target)
            self.assertFalse((Path(directory) / 'escape.json').exists())
