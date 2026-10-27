"""Receipt reuse verifies provenance and bytes instead of translating failure to pass."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager import Phase
from build_manager.evidence import EvidenceCache


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = EvidenceCache(self.root / 'cache')
        self.calls = 0

    def execute(self, name, *, key='a' * 64, status='passed'):
        output = self.root / name
        output.mkdir()
        phase = Phase(name, ('python', 'tests.py'), str(self.root), effect='test',
                      reuse_key=key, artifacts=(str(output / 'original.xml'),))
        def action():
            self.calls += 1
            artifact = output / 'original.xml'
            artifact.write_text('<testsuite/>')
            return dict(id=name, status=status, required=True, seconds=12,
                        artifacts=[dict(path=str(artifact), original_path=str(artifact),
                            sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), kind='junit')])
        return self.cache.execute(phase, output, action)

    def test_pass_reuses_bytes_and_records_original_duration_and_provenance(self):
        self.execute('first')
        row = self.execute('second')
        self.assertEqual(self.calls, 1)
        self.assertTrue(row['reused'])
        self.assertEqual(row['seconds'], 0)
        self.assertEqual(row['reuse']['original_seconds'], 12)
        self.assertEqual(row['reuse']['step'], 'first')
        self.assertEqual(Path(row['artifacts'][0]['original_path']).read_text(), '<testsuite/>')

    def test_changed_inputs_failures_and_cancelled_results_are_never_reused(self):
        self.execute('failed', status='failed')
        self.execute('cancelled', status='cancelled')
        self.execute('passed')
        self.execute('changed', key='b' * 64)
        self.assertEqual(self.calls, 4)

    def test_modified_receipt_or_artifact_causes_execution(self):
        self.execute('first')
        path = self.root / 'cache' / ('a' * 64 + '.json')
        receipt = json.loads(path.read_text())
        receipt['payload']['row']['seconds'] = 0
        path.write_text(json.dumps(receipt))
        self.assertNotIn('reused', self.execute('second'))
        (self.root / 'second/original.xml').write_text('changed bytes')
        self.assertNotIn('reused', self.execute('third'))
        self.assertEqual(self.calls, 3)

    def test_effects_and_cleanup_cannot_declare_reuse(self):
        phase = Phase('test', ('python', 'tests.py'), str(self.root), effect='test', reuse_key='a' * 64)
        for changes in ({'effect': 'deploy'}, {'kind': 'build'}, {'always': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(phase, **changes)
