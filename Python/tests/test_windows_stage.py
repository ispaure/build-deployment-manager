"""Bound source extraction to one admission and reconcile only durable evidence."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from build_manager.windows_guest import WindowsGuest, STAGE, STAGE_STATE
from build_manager.parallels import Parallels

LOST = 'Windows guest command failed (255): PrlJob_GetResult: Invalid argument'


class StageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.guest = WindowsGuest(Mock(), 'vm', 'workspace', 'token', 'operation')
        self.receipt = dict(state='complete', token='token', operation='operation',
                            folder='source', sha256=hashlib.sha256(b'zip').hexdigest())

    def test_lost_completion_adopts_exact_receipt_without_second_extraction(self):
        with patch.object(self.guest, 'call', side_effect=[RuntimeError(LOST), json.dumps(self.receipt)]) as call:
            self.guest.stage('source', b'zip')
        self.assertEqual([c.args[0] for c in call.call_args_list], [STAGE, STAGE_STATE])

    def test_lost_admission_retries_same_identity_only_after_absence(self):
        with patch.object(self.guest, 'call', side_effect=[RuntimeError(LOST),
                '{"state":"absent"}', json.dumps(self.receipt)]) as call:
            self.guest.stage('source', b'zip')
        self.assertEqual([c.args[0] for c in call.call_args_list], [STAGE, STAGE_STATE, STAGE])
        self.assertEqual(call.call_args_list[0], call.call_args_list[2])

    def test_pending_admission_is_observed_without_reextracting(self):
        with patch.object(self.guest, 'call', side_effect=[RuntimeError(LOST),
                '{"state":"pending"}', json.dumps(self.receipt)]) as call, \
             patch('build_manager.windows_guest.time.sleep'):
            self.guest.stage('source', b'zip')
        self.assertEqual(sum(c.args[0] == STAGE for c in call.call_args_list), 1)

    def test_stale_or_changed_receipt_is_never_adopted(self):
        for key in ('token', 'operation', 'folder', 'sha256'):
            changed = dict(self.receipt, **{key: 'wrong'})
            with self.subTest(key=key), patch.object(self.guest, 'call', return_value=json.dumps(changed)):
                with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                    self.guest.stage('source', b'zip')

    def test_unknown_completion_remains_bounded_and_nontransport_error_not_replayed(self):
        with patch.object(self.guest, 'call', return_value='{"state":"pending"}') as call, \
             patch('build_manager.windows_guest.time.monotonic', side_effect=[0, 31]):
            with self.assertRaisesRegex(RuntimeError, 'unknown'):
                self.guest.stage('source', b'zip')
        self.assertEqual(call.call_count, 1)
        with patch.object(self.guest, 'call', side_effect=RuntimeError('Ownership mismatch')) as call:
            with self.assertRaisesRegex(RuntimeError, 'Ownership'):
                self.guest.stage('source', b'zip')
        self.assertEqual(call.call_count, 1)


class LocalPowerShell:
    def __init__(self):
        self.loss = None
        self.stage_calls = 0
        self.slow = False

    def powershell(self, vm, script, values, *, data=None, timeout=60):
        if script == STAGE:
            self.stage_calls += 1
            if self.loss == 'before':
                self.loss = None
                raise RuntimeError(LOST)
            script = script.replace(' Expand-Archive -LiteralPath',
                " [IO.File]::AppendAllText((OwnedPath 'extract-count'),'x'); Expand-Archive -LiteralPath")
            if self.slow:
                script = script.replace(' Expand-Archive -LiteralPath',
                                        ' Start-Sleep -Seconds 6; Expand-Archive -LiteralPath')
        command = Parallels('unused-local-loader').powershell_command('00000000-0000-0000-0000-000000000001')[4:]
        result = subprocess.run(command, input=Parallels.powershell_payload(script, values, data),
                                capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
        if self.loss == 'after' and 'Expand-Archive -LiteralPath' in script:
            self.loss = None
            raise RuntimeError(LOST)
        return result.stdout


@unittest.skipUnless(os.name == 'nt', 'Real Windows PowerShell and file-sharing semantics')
class NativeStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'token'
        self.root.mkdir()
        (self.root / '.manager-owned.json').write_text('{"token":"token"}')
        self.client = LocalPowerShell()
        self.guest = WindowsGuest(self.client, 'vm', str(self.root), 'token', 'operation')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('nested/value.txt', 'actual extracted bytes')
        self.payload = stream.getvalue()

    def test_lost_completion_and_duplicate_admit_one_real_extractor(self):
        self.client.loss = 'after'
        self.guest.stage('source', self.payload)
        self.guest.stage('source', self.payload)
        self.assertEqual((self.root / 'extract-count').read_text(), 'x')
        self.assertEqual((self.root / 'source/nested/value.txt').read_text(), 'actual extracted bytes')
        self.guest.remove_paths(['source', 'source.zip'])
        self.assertFalse((self.root / 'source').exists())
        self.assertTrue((self.root / 'source.manager-stage.claim').exists())
        with self.assertRaisesRegex(RuntimeError, 'retired'):
            self.guest.stage('source', self.payload)
        self.assertEqual((self.root / 'extract-count').read_text(), 'x')

    def test_loss_before_admission_retries_without_duplicate_extraction(self):
        self.client.loss = 'before'
        self.guest.stage('source', self.payload)
        self.assertEqual(self.client.stage_calls, 2)
        self.assertEqual((self.root / 'extract-count').read_text(), 'x')

    def test_cleanup_fences_a_request_that_has_not_been_admitted(self):
        self.guest.remove_paths(['source', 'source.zip'])
        self.assertTrue((self.root / 'source.manager-stage.claim').exists())
        # A delayed request observes the tombstone and admits no extractor.
        response = json.loads(self.guest.call(STAGE, values=dict(folder='source',
            sha256=hashlib.sha256(self.payload).hexdigest()), data=self.payload))
        self.assertEqual(response, {'state': 'pending'})
        self.assertFalse((self.root / 'source').exists())
        self.assertFalse((self.root / 'extract-count').exists())

    def test_cleanup_cannot_delete_an_active_extractor(self):
        self.client.slow = True
        errors = []
        def stage():
            try:
                self.guest.stage('source', self.payload)
            except BaseException as error:
                errors.append(error)
        thread = Thread(target=stage)
        thread.start()
        self.addCleanup(thread.join)
        deadline = time.monotonic() + 10
        while not (self.root / 'source.manager-stage.claim').exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        with self.assertRaisesRegex(RuntimeError, 'extractor still owns'):
            self.guest.remove_paths(['source', 'source.zip'])
        thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.guest.remove_paths(['source', 'source.zip'])
        self.assertFalse((self.root / 'source').exists())
