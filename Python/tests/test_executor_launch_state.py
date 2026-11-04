"""Durable boundary proof distinguishes safe admission retries from unknown effects."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Executor, Phase, Plan
from build_manager.api import run_plan
from build_manager.locking import workspace_lock
from build_manager.workflows import recover_phase_records


class LaunchStateTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'result'

    def plan(self, *, argv=None, resources=None):
        marker = self.root / 'launched'
        code = f'from pathlib import Path;Path({str(marker)!r}).write_text("launched");print("done")'
        phase = Phase('provider', tuple(argv or (sys.executable, '-c', code)), str(self.root),
                      effect='upload', provider='firebase', approval_required=False, resources=resources or {})
        return Plan('Fixture', 'launch boundary', {}, (phase,), str(self.root / 'workspace'))

    def journal(self, row):
        value = json.loads((self.output / row['launch_record']).read_text())
        self.assertEqual(value['schema'], 1)
        self.assertEqual(value['phase'], row['id'])
        self.assertEqual(value['operation_id'], row['operation_id'])
        self.assertEqual(value['state'], row['launch_state'])
        return value

    def test_actual_resource_lock_path_error_is_durable_not_started_and_retryable(self):
        # Real filesystem admission failure, before run_phase or a child exists.
        blocked = self.root / 'not-a-directory'
        blocked.write_text('preserve')
        plan = self.plan(resources={'provider:fixture': 1})
        with patch.object(Executor, 'run_phase', side_effect=AssertionError('must not launch')) as launch:
            failed = Executor(resource_directory=blocked).run(plan, self.output)
        launch.assert_not_called()
        row = failed['phases'][0]
        self.assertEqual((failed['status'], row['status'], row['launch_state']),
                         ('failed', 'failed', 'not_started'))
        self.assertTrue(row['retryable'])
        self.journal(row)
        self.assertFalse((self.root / 'launched').exists())
        self.assertEqual(blocked.read_text(), 'preserve')
        result = Executor(resource_directory=self.root / 'slots').run(plan, self.output, resume=True)
        self.assertEqual(result['status'], 'passed')
        self.assertNotEqual(row['operation_id'], result['phases'][0]['operation_id'])
        self.journal(row)  # A subsequent attempt never overwrites the old proof.
        self.assertEqual((self.root / 'launched').read_text(), 'launched')

    @unittest.skipIf(os.name == 'nt', 'POSIX exec-error proof; Windows constructor remains conservative')
    def test_actual_missing_executable_is_failed_not_started_without_effect(self):
        result = Executor().run(self.plan(argv=[str(self.root / 'absent-command')]), self.output)
        row = result['phases'][0]
        self.assertEqual((result['status'], row['status'], row['launch_state']),
                         ('failed', 'failed', 'not_started'))
        self.assertTrue(row['retryable'])
        self.journal(row)
        self.assertFalse((self.root / 'launched').exists())

    @unittest.skipIf(os.name == 'nt', 'Actual POSIX Popen boundary')
    def test_launching_journal_is_persisted_before_constructor(self):
        plan = self.plan()
        original = subprocess.Popen
        inspected = []
        def spawn(argv, *args, **kwargs):
            if list(argv) == list(plan.phases[0].argv):
                records = list(self.output.glob('provider.*.launch.json'))
                self.assertEqual(len(records), 1)
                journal = json.loads(records[0].read_text())
                intent = json.loads((self.output / 'result.json').read_text())['phases'][0]
                self.assertEqual(journal['state'], 'launching')
                self.assertEqual(journal['operation_id'], intent['operation_id'])
                self.assertEqual(intent['status'], 'running')
                inspected.append(journal)
            return original(argv, *args, **kwargs)
        with patch('build_manager.executor.subprocess.Popen', side_effect=spawn):
            result = Executor().run(plan, self.output)
        self.assertEqual(len(inspected), 1)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['phases'][0]['launch_state'], 'started')
        self.journal(result['phases'][0])

    def test_postlaunch_observer_exception_keeps_external_outcome_unknown(self):
        def observe(event):
            if event.get('type') == 'output':
                raise RuntimeError('lost observer after child output')
        result = Executor(event=observe).run(self.plan(), self.output)
        row = result['phases'][0]
        self.assertEqual((result['status'], row['status'], row['launch_state']),
                         ('unknown', 'unknown', 'started'))
        self.assertNotIn('retryable', row)
        self.assertTrue((self.root / 'launched').exists())
        self.journal(row)

    @unittest.skipIf(os.name == 'nt', 'Actual POSIX constructor boundary')
    def test_unproven_constructor_exception_does_not_claim_not_started(self):
        plan = self.plan()
        original = subprocess.Popen
        def spawn(argv, *args, **kwargs):
            if list(argv) == list(plan.phases[0].argv):
                raise RuntimeError('uncertain constructor boundary')
            return original(argv, *args, **kwargs)
        with patch('build_manager.executor.subprocess.Popen', side_effect=spawn):
            result = Executor().run(plan, self.output)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['phases'][0]['launch_state'], 'launching')
        self.journal(result['phases'][0])

    def test_launch_intent_persistence_failure_stops_before_constructor_and_is_conservative(self):
        from build_manager.profiles import save_json
        def persist(path, value):
            if str(path).endswith('.launch.json') and value['state'] == 'launching':
                raise PermissionError('launch proof cannot be persisted')
            return save_json(path, value)
        with patch('build_manager.profiles.save_json', side_effect=persist):
            result = Executor().run(self.plan(), self.output)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['phases'][0]['launch_state'], 'unknown')
        self.assertFalse((self.root / 'launched').exists())
        self.assertNotIn('retryable', result['phases'][0])

    def test_legacy_unknown_and_interrupted_intents_are_not_auto_reclassified(self):
        plan = self.plan()
        for status in ('unknown', 'running'):
            for extra in ({}, {'launch_state': 'not_started'}):
                with self.subTest(status=status, extra=extra):
                    row = dict(id='provider', status=status, seconds=0, **extra)
                    report = dict(schema=1, plan_identity=plan.identity, phases=[row])
                    recovered = recover_phase_records(plan, report, preserve_unknown=True)
                    self.assertEqual(recovered[0]['status'], 'unknown')
                    with self.assertRaisesRegex(ValueError, 'reconciliation'):
                        recover_phase_records(plan, report)

    def test_neutral_api_reconciles_under_supervisor_lock_without_replaying_effect(self):
        plan = self.plan(argv=[sys.executable, '-c', 'raise SystemExit(7)'])
        first = run_plan(plan, self.output)
        self.assertEqual(first['status'], 'unknown')
        calls = []
        def reconcile(name, row):
            with self.assertRaisesRegex(RuntimeError, 'owns'):
                with workspace_lock(self.output / 'supervisor.lock'):
                    self.fail('reconcile must hold the supervisor lock')
            calls.append((name, row['operation_id']))
            return dict(status='passed', provider_receipt='verified-fixture')
        with patch.object(Executor, 'run_phase', side_effect=AssertionError('must not replay')):
            result = run_plan(plan, self.output, resume=True, reconcile=reconcile)
        self.assertEqual(calls, [('provider', first['phases'][0]['operation_id'])])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['phases'][0]['receipt']['provider_receipt'], 'verified-fixture')

    def test_not_performed_receipt_keeps_existing_interrupted_contract(self):
        plan = self.plan()
        row = dict(id='provider', status='unknown')
        report = dict(schema=1, plan_identity=plan.identity, phases=[row])
        recovered = recover_phase_records(plan, report, reconcile=lambda *_: dict(status='not-performed'))
        self.assertEqual(recovered[0]['status'], 'interrupted')
        self.assertEqual(recovered[0]['receipt'], {'status': 'not-performed'})
