"""Real source extractors survive lost sessions without replaying admitted work."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from build_manager.parallels import Parallels, STAGE, REMOVE

ERROR = 'Guest command failed (255); PrlJob_GetRetCode: Invalid argument.'


@unittest.skipUnless(os.name == 'posix', 'Linux staging uses POSIX ownership and leases')
class LinuxStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'input'
        self.source.mkdir()
        (self.source / 'fixture.txt').write_text('the exact selected source')
        self.token = 'a' * 32
        self.workspace = self.root / self.token
        self.client = Parallels('/fixture/prlctl')
        self.executions = 0

    def execute(self, selector, argv, *, data=None, timeout=60):
        result = subprocess.run([sys.executable, *argv[1:]], input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f'Guest command failed ({result.returncode}): ' + result.stderr.decode())
        return result.stdout

    def stage(self, execute):
        with patch.object(self.client, 'execute', side_effect=execute):
            return self.client.stage('fixture', self.source, str(self.workspace), self.token,
                                     os.getuid(), os.getgid(), members=['fixture.txt'])

    def assert_complete(self, digest):
        receipt = json.loads((self.workspace / '.manager-stage.json').read_text())
        self.assertEqual(receipt['archive_sha256'], digest)
        self.assertEqual(receipt['token'], self.token)
        self.assertEqual((self.workspace / 'source/fixture.txt').read_text(), 'the exact selected source')

    def test_lost_session_before_admission_retries_only_absent_workspace(self):
        def execute(selector, argv, **options):
            if argv[2] == STAGE:
                self.executions += 1
                if self.executions == 1:
                    raise RuntimeError(ERROR)
            return self.execute(selector, argv, **options)
        self.assert_complete(self.stage(execute))
        self.assertEqual(self.executions, 2)

    def test_lost_session_after_completion_adopts_bound_receipt_without_extraction(self):
        def execute(selector, argv, **options):
            if argv[2] == STAGE:
                self.executions += 1
                self.execute(selector, argv, **options)
                raise RuntimeError(ERROR)
            return self.execute(selector, argv, **options)
        self.assert_complete(self.stage(execute))
        self.assertEqual(self.executions, 1)

    def test_delayed_original_admission_cannot_be_overwritten_by_retry(self):
        original = None
        def execute(selector, argv, **options):
            nonlocal original
            if argv[2] == STAGE:
                self.executions += 1
                if self.executions == 1:
                    original = (selector, argv, options)
                    raise RuntimeError(ERROR)
                # Admission can arrive after the read-only absent inspection.
                self.execute(original[0], original[1], **original[2])
            return self.execute(selector, argv, **options)
        self.assert_complete(self.stage(execute))
        self.assertEqual(self.executions, 2)

    def test_admitted_transfer_without_completion_is_never_extracted_again(self):
        def execute(selector, argv, **options):
            if argv[2] == STAGE:
                self.executions += 1
                partial = STAGE[:STAGE.index(' with tarfile.open')]
                self.execute(selector, [*argv[:2], partial, *argv[3:]], **options)
                raise RuntimeError(ERROR)
            return self.execute(selector, argv, **options)
        with patch('build_manager.parallels.time.monotonic', side_effect=[0, 31]):
            with self.assertRaisesRegex(RuntimeError, 'completion is unknown'):
                self.stage(execute)
        self.assertEqual(self.executions, 1)
        self.assertTrue((self.workspace / '.manager-owned.json').exists())
        self.assertFalse((self.workspace / '.manager-stage.json').exists())

    def test_changed_completion_identity_is_rejected_without_replay(self):
        def execute(selector, argv, **options):
            if argv[2] == STAGE:
                self.executions += 1
                self.execute(selector, argv, **options)
                path = self.workspace / '.manager-stage.json'
                record = json.loads(path.read_text()); record['archive_sha256'] = 'foreign'
                path.write_text(json.dumps(record))
                raise RuntimeError(ERROR)
            return self.execute(selector, argv, **options)
        with self.assertRaisesRegex(RuntimeError, 'completion identity changed'):
            self.stage(execute)
        self.assertEqual(self.executions, 1)

    def test_nontransport_failure_is_not_replayed(self):
        def execute(selector, argv, **options):
            self.executions += 1
            raise RuntimeError('Source transfer digest mismatch')
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            self.stage(execute)
        self.assertEqual(self.executions, 1)

    def test_inflight_transfer_is_reconciled_and_cleanup_waits_for_its_lease(self):
        process = None
        delayed = STAGE.replace(' with tarfile.open', ' import time;time.sleep(.4)\n with tarfile.open')
        def execute(selector, argv, **options):
            nonlocal process
            if argv[2] == delayed:
                self.executions += 1
                process = subprocess.Popen([sys.executable, *argv[1:]], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.stdin.write(options['data']); process.stdin.close()
                deadline = time.monotonic() + 5
                while not (self.workspace / '.manager-owned.json').exists():
                    if time.monotonic() >= deadline:
                        self.fail('Extractor did not publish its admission')
                    time.sleep(.01)
                raise RuntimeError(ERROR)
            return self.execute(selector, argv, **options)
        try:
            with patch('build_manager.parallels.STAGE', delayed):
                self.assert_complete(self.stage(execute))
            self.assertEqual(self.executions, 1)
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill(); process.wait()
                process.stdout.close(); process.stderr.close()

    def test_cleanup_does_not_remove_active_extractor(self):
        digest = self.stage(self.execute)
        self.assert_complete(digest)
        import fcntl
        with open(self.workspace / '.manager-stage.lock', 'rb') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            bounded = REMOVE.replace('time.monotonic()+3', 'time.monotonic()+.1')
            with self.assertRaisesRegex(RuntimeError, 'active; cleanup deferred'):
                self.execute('fixture', ['python3', '-c', bounded, str(self.workspace), self.token])
            self.assertTrue((self.workspace / '.manager-owned.json').exists())
        self.execute('fixture', ['python3', '-c', REMOVE, str(self.workspace), self.token])
        self.assertFalse(self.workspace.exists())
