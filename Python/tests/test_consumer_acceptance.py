"""Cross-consumer evidence binds explicit sources, interpreters and completion."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Executor
from build_manager.consumer_acceptance import prepare, verify
from commonUtils.runtime.streams import file_sha256


class ConsumerAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'consumer'
        self.root.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(self.root)], check=True)
        (self.root / 'source.py').write_text('VALUE = 1\n')
        subprocess.run(['git', '-C', str(self.root), 'add', 'source.py'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'fixture'], check=True)
        self.config = dict(schema=1, baseline=str(self.root), checks=[dict(id='consumer',
            root=str(self.root), shared=str(self.root), interpreter=sys.executable,
            argv=['-c', 'print("portable fixture")'], environment={'PYTHONPATH': ''})])
        self.output = self.directory / 'acceptance'

    def test_ordinary_plan_executes_and_checks_identity_before_and_after(self):
        plan = prepare(self.config, self.output)
        self.assertEqual({phase.effect for phase in plan.phases}, {'test', 'inspect'})
        self.assertEqual(plan.phases[1].argv[0], sys.executable)
        self.assertEqual(plan.phases[1].environment['PYTHONPATH'], '')
        result = Executor().run(plan, self.output / 'run')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['phases'][-1]['id'], 'verify-completion')

    def test_modified_capture_and_changed_source_cannot_be_accepted(self):
        prepare(self.config, self.output)
        captured = self.output / 'inputs.json'
        digest = file_sha256(captured)
        verify(captured, digest)
        (self.root / 'source.py').write_text('VALUE = 2\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify(captured, digest)
        captured.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'capture changed'):
            verify(captured, digest)

    def test_failed_consumer_still_checks_final_source_and_remains_failed(self):
        self.config['checks'][0]['argv'] = ['-c', 'raise SystemExit(7)']
        plan = prepare(self.config, self.output)
        result = Executor().run(plan, self.output / 'run')
        self.assertEqual(result['status'], 'failed')
        facts = {row['id']: row for row in result['phases']}
        self.assertEqual(facts['consumer']['exit_code'], 7)
        self.assertEqual(facts['verify-completion']['status'], 'passed')

    def test_branch_and_output_selection_never_fall_back(self):
        self.config['checks'][0]['branch'] = 'not-this-branch'
        with self.assertRaisesRegex(ValueError, 'branch'):
            prepare(self.config, self.output)
        self.assertFalse(self.output.exists())
        self.config['checks'][0].pop('branch')
        prepare(self.config, self.output)
        with self.assertRaisesRegex(ValueError, 'fresh'):
            prepare(self.config, self.output)
