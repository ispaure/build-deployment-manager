"""Retirement preserves evidence/outcomes, serializes with execution and survives interruption."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan
from build_manager.executor import Executor
from build_manager.history import load_run, recent_runs
from build_manager.locking import workspace_lock
from build_manager.retention import set_workflow_hold, has_retention_protection
from build_manager.run_retirement import list_held_or_retired_runs, retire_run
from build_manager.workflows import recover_phase_records


class RunRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runs = self.root / 'runs'
        self.output = self.runs / 'old'
        self.output.mkdir(parents=True)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.plan = Plan('Fixture', 'Deliver', {},
            (Phase('upload', (sys.executable, '-c', 'raise SystemExit(99)'), str(self.root),
                   effect='upload', artifacts=(str(self.workspace / 'app.zip'),)),), str(self.workspace))
        self.plan.save(self.output / 'plan.json')
        self.report = dict(schema=1, plan_identity=self.plan.identity, status='unknown',
            phases=[dict(id='upload', status='unknown', operation_id='recorded-intent',
                         receipt=dict(status='unknown', provider='fixture'))],
            holds=[str(self.workspace), str(self.output)])
        self.save()
        for path in self.report['holds']:
            set_workflow_hold(path, str(self.output))
        (self.output / 'upload.log').write_text('retained provider response')

    def save(self):
        (self.output / 'result.json').write_text(json.dumps(self.report))

    def test_retire_preserves_unknown_outcome_and_other_owners_and_blocks_resume(self):
        set_workflow_hold(self.workspace, 'other-workflow')
        self.assertEqual(list_held_or_retired_runs(self.runs)[0]['holds'], 2)
        with self.assertRaisesRegex(ValueError, 'confirm'):
            retire_run(self.runs, 'old')
        result = retire_run(self.runs, 'old', confirmed=True)
        self.assertEqual(result['released_holds'], 2)
        plan, report = load_run(self.output / 'result.json')
        self.assertEqual(report['status'], 'unknown')
        self.assertEqual(report['phases'], self.report['phases'])
        self.assertEqual(report['holds'], [])
        self.assertTrue(has_retention_protection(self.workspace))
        self.assertEqual((self.output / 'upload.log').read_text(), 'retained provider response')
        self.assertTrue(recent_runs(self.runs)[0]['retired'])
        with self.assertRaisesRegex(ValueError, 'retired'):
            recover_phase_records(plan, report, preserve_unknown=True)
        before = (self.output / 'result.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'retired'):
            Executor().run(plan, self.output, resume=True)
        self.assertEqual((self.output / 'result.json').read_bytes(), before)

    def test_active_run_and_undeclared_holds_cannot_be_retired(self):
        with workspace_lock(self.output / 'supervisor.lock'), self.assertRaisesRegex(RuntimeError, 'owns'):
            retire_run(self.runs, 'old', confirmed=True)
        self.report['holds'].append(str(self.root / 'foreign'))
        self.save()
        with self.assertRaisesRegex(ValueError, 'disagree'):
            retire_run(self.runs, 'old', confirmed=True)
        self.assertNotIn('retirement', load_run(self.output / 'result.json')[1])
        with self.assertRaises(ValueError):
            retire_run(self.runs, '../workspace', confirmed=True)

    def test_interrupted_retirement_can_finish_without_enabling_continuation(self):
        with patch('build_manager.run_retirement.release_workflow_hold', side_effect=OSError('fixture disk error')):
            with self.assertRaises(OSError):
                retire_run(self.runs, 'old', confirmed=True)
        report = load_run(self.output / 'result.json')[1]
        self.assertTrue(report['retirement'])
        self.assertTrue(report['holds'])
        result = retire_run(self.runs, 'old', confirmed=True)
        self.assertEqual(result['released_holds'], 2)
        self.assertFalse(has_retention_protection(self.workspace))


class StorageMaintenanceTests(unittest.TestCase):
    def test_maintenance_runs_after_execution_leases_and_does_not_rewrite_outcome(self):
        from build_manager.api import run_plan
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = Plan('Fixture', 'Check', {}, (Phase('check', (sys.executable, '-c', 'pass'), str(root)),),
                        str(root / 'workspace'))
            def maintenance(prepared):
                with workspace_lock(root / 'workspace/operation.lock'):
                    raise ValueError('fixture maintenance failure')
            report = run_plan(plan, root / 'run', maintenance=maintenance)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(report['storage_maintenance']['status'], 'failed')
            self.assertEqual(load_run(root / 'run/result.json')[1]['status'], 'passed')
            self.assertEqual(json.loads((root / 'run/storage-maintenance.json').read_text())['status'], 'failed')
