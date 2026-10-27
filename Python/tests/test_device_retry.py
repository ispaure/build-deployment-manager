"""Explicit device retry preserves unknown intent and revalidates prepared inputs."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Phase, Plan
from build_manager.device_retry import candidates, inspect, prepare
from build_manager.api import run_plan, review_run


class DeviceRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'original'
        self.output.mkdir()
        self.app = self.root / 'app.bin'
        self.app.write_bytes(b'exact prepared app')
        self.receipt = self.root / 'device.json'
        self.intent = self.receipt.with_suffix('.attempt.json')
        self.intent.write_text('unknown original intent')
        command = 'from pathlib import Path; import sys; Path(sys.argv[1]).parent.mkdir(parents=True,exist_ok=True); Path(sys.argv[1]).write_text("installed")'
        self.plan = Plan('Fixture', 'devices', {'commit': 'fixed'}, (
            Phase('prepare', (sys.executable, '-c', 'pass'), str(self.root), effect='build'),
            Phase('install-ipad', (sys.executable, '-c', command, str(self.receipt)), str(self.root),
                effect='deploy', dependencies=('prepare',), artifacts=(str(self.receipt),)),
            Phase('install-phone', (sys.executable, '-c', 'raise Exception("must not repeat")'),
                str(self.root), effect='deploy')), str(self.root / 'workspace'))
        self.report = dict(schema=1, status='unknown', plan_identity=self.plan.identity, phases=[
            dict(id='prepare', status='passed', artifacts=[dict(path=str(self.app), sha256=hashlib.sha256(self.app.read_bytes()).hexdigest())]),
            dict(id='install-ipad', status='unknown'), dict(id='install-phone', status='passed')])
        self.save()

    def save(self):
        self.plan.save(self.output / 'plan.json')
        (self.output / 'result.json').write_text(json.dumps(self.report))

    def test_new_attempt_reviews_exact_inputs_and_preserves_original(self):
        before = (self.output / 'result.json').read_bytes()
        retry = prepare(self.output, 'install-ipad')
        self.assertEqual(retry.source, self.plan.source)
        self.assertEqual(len(retry.phases), 2)
        self.assertNotEqual(retry.phases[-1].artifacts[0], str(self.receipt))
        output = self.root / 'retry'
        pending = run_plan(retry, output, confirmed=True)
        self.assertEqual(pending['status'], 'awaiting_review')
        self.assertFalse(Path(retry.phases[-1].artifacts[0]).exists())
        review = review_run(output)
        approvals = {row['step']: row['identity'] for row in review['approvals']}
        done = run_plan(retry, output, confirmed=True, resume=True, approval_identities=approvals)
        self.assertEqual(done['status'], 'passed')
        self.assertEqual(Path(retry.phases[-1].artifacts[0]).read_text(), 'installed')
        self.assertEqual((self.output / 'result.json').read_bytes(), before)
        self.assertEqual(self.intent.read_text(), 'unknown original intent')
        self.assertFalse(self.receipt.exists())

    def test_changed_original_or_prepared_bytes_block_retry(self):
        digest = inspect(self.output, 'install-ipad')[-1]
        self.report['phases'][-1]['status'] = 'unknown'
        self.save()
        with self.assertRaisesRegex(ValueError, 'changed'):
            inspect(self.output, 'install-ipad', digest)
        self.app.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'artifact'):
            prepare(self.output, 'install-ipad')

    def test_uploads_failed_preparation_and_active_runs_not_eligible(self):
        for effect, status, preparation in [('upload', 'unknown', 'passed'),
                ('deploy', 'running', 'passed'), ('deploy', 'unknown', 'failed')]:
            with self.subTest(effect=effect, status=status, preparation=preparation):
                plan = replace(self.plan, phases=(self.plan.phases[0], replace(self.plan.phases[1], effect=effect)))
                report = dict(status=status, phases=[dict(id='prepare', status=preparation), dict(id='install-ipad', status='unknown')])
                self.assertEqual(candidates(plan, report), [])

    def test_changed_inputs_after_planning_prevent_any_install(self):
        retry = prepare(self.output, 'install-ipad')
        self.app.write_bytes(b'tampered after review')
        result = run_plan(retry, self.root / 'retry', confirmed=True)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(Path(retry.phases[-1].artifacts[0]).exists())
