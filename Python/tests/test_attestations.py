"""Actual SSH signatures over authentic local cache entries, with fail-closed bindings."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from build_manager import Phase
from build_manager.attestations import export_receipts, verify_export
from build_manager.evidence import EvidenceCache


@unittest.skipUnless(shutil.which('ssh-keygen'), 'SSH signing tool unavailable')
class AttestationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / 'signing'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.private)],
                       check=True, capture_output=True)
        self.allowed = self.root / 'allowed-signers'
        self.allowed.write_text('release-local ' + self.private.with_suffix('.pub').read_text())
        self.now = datetime.now(timezone.utc)
        self.cache = EvidenceCache(self.root / 'cache')
        self.phase = Phase('suite', ('python', 'test.py'), str(self.root),
                           effect='test', reuse_key='a' * 64,
                           artifacts=(str(self.root / 'report.xml'),))
        artifact = self.root / 'report.xml'
        artifact.write_text('<testsuite tests="1" failures="0"/>')
        self.row = dict(id='suite', status='passed', finished_at=self.now.isoformat(),
                        artifacts=[dict(path=str(artifact), original_path=str(artifact), kind='junit',
                                        sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())])
        self.cache.execute(self.phase, self.root, lambda: self.row)
        self.bindings = dict(repository='owner/project', source='b' * 40,
                             dependencies={'commonUtils': 'c' * 40},
                             platform='macOS-arm64', toolchain='d' * 64)

    def export(self):
        return export_receipts(self.cache, [self.phase], self.bindings, self.private, now=self.now)

    def verify(self, envelope, **changes):
        args = dict(now=self.now)
        args.update(changes)
        return verify_export(envelope, self.allowed, 'release-local', self.bindings,
                             {'suite': 'a' * 64}, **args)

    def test_authentic_receipt_verifies_without_private_machine_paths(self):
        envelope = self.export()
        self.assertEqual(self.verify(envelope)['tests'][0]['inputs'], 'a' * 64)
        self.assertNotIn(str(self.root), json.dumps(envelope))
        self.assertEqual(envelope['payload']['bindings'], self.bindings)

    def test_tampered_signature_wrong_signer_or_changed_source_cannot_pass(self):
        envelope = self.export()
        envelope['payload']['tests'][0]['artifacts'][0]['sha256'] = '0' * 64
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify(envelope)
        envelope = self.export()
        envelope['payload']['bindings']['source'] = 'e' * 40
        with self.assertRaises(ValueError):
            self.verify(envelope)
        self.allowed.write_text('different-signer ' + self.private.with_suffix('.pub').read_text())
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify(self.export())

    def test_missing_or_corrupt_local_receipt_cannot_be_exported(self):
        (self.root / 'report.xml').write_text('changed')
        with self.assertRaises(ValueError):
            self.export()

    def test_additional_signed_tests_require_opt_in_and_matching_required_inputs(self):
        from dataclasses import replace
        extra = replace(self.phase, id='extra', reuse_key='e' * 64)
        self.cache.execute(extra, self.root, lambda: dict(self.row, id='extra'))
        envelope = export_receipts(self.cache, [self.phase, extra], self.bindings,
                                   self.private, now=self.now)
        with self.assertRaises(ValueError):
            self.verify(envelope)
        self.assertEqual(len(self.verify(envelope, allow_additional_tests=True)['tests']), 2)
        for expected in ({'missing': 'a' * 64}, {'suite': 'f' * 64}):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                verify_export(envelope, self.allowed, 'release-local', self.bindings,
                              expected, now=self.now, allow_additional_tests=True)
        envelope['payload']['tests'].append(envelope['payload']['tests'][0])
        with self.assertRaises(ValueError):
            self.verify(envelope, allow_additional_tests=True)

    def test_stale_future_or_different_required_coverage_runs_fresh(self):
        envelope = self.export()
        for now in (self.now + timedelta(days=2), self.now - timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                self.verify(envelope, now=now)
        with self.assertRaises(ValueError):
            verify_export(envelope, self.allowed, 'release-local', self.bindings,
                          {'suite': 'e' * 64}, now=self.now)

    def test_reexport_does_not_extend_original_completion_lifetime(self):
        future = self.now + timedelta(days=2)
        envelope = export_receipts(self.cache, [self.phase], self.bindings, self.private, now=future)
        with self.assertRaises(ValueError):
            self.verify(envelope, now=future)

    def test_wrong_platform_or_toolchain_does_not_match_even_signed_evidence(self):
        envelope = self.export()
        for name in ('platform', 'toolchain'):
            expected = dict(self.bindings, **{name: 'different'})
            with self.assertRaises(ValueError):
                verify_export(envelope, self.allowed, 'release-local', expected,
                              {'suite': 'a' * 64}, now=self.now)

