"""Portable recovery acceptance using real harmless subprocesses, never devices."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from build_manager import Executor, Phase, Plan


class InfrastructureRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / 'prepared.app'
        self.app.write_bytes(b'original app')
        self.proof = dict(schema=1, target='owned-fixture', state='stopped',
                          failure_kind='infrastructure',
                          owned=True, exclusive=True, worker_stopped=True, held=False)
        self.proof_path = self.root / 'proof.json'
        self.proof_path.write_text(json.dumps(self.proof))
        self.policy = dict(environment='android', target='owned-fixture', resource='fixture:owned',
            safe_to_repeat=True, timeout=5,
            inputs={str(self.app): hashlib.sha256(self.app.read_bytes()).hexdigest()},
            probe=self.command("from pathlib import Path; print(Path('proof.json').read_text())"),
            recover=self.command("import json,os; from pathlib import Path; "
                "p=Path('proof.json'); d=json.loads(p.read_text()); d['state']='ready'; "
                "p.write_text(json.dumps(d)); Path('repair').write_text(os.environ['BUILD_MANAGER_RECOVERY_ACTION'])"))
        self.code = "from pathlib import Path; p=Path('runs'); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); print('attempt',n); raise SystemExit(7 if n==1 else 0)"

    def command(self, code):
        return (sys.executable, '-c', code)

    def phase(self, **options):
        values = dict(effect='test', resources={'fixture:owned': 1}, infrastructure_recovery=self.policy)
        values.update(options)
        return Phase('native', self.command(self.code), str(self.root), **values)

    def execute(self, phase=None, *, event=None, cancelled=None, resume=False, extra=()):
        plan = Plan('fixture', 'test', {'revision': 'fixture'}, (phase or self.phase(), *extra), str(self.root / 'workspace'))
        executor = Executor(event=event, cancelled=cancelled,
            resource_directory=self.root / 'resources', evidence_directory=self.root / 'cache')
        return executor.run(plan, self.root / 'result', resume=resume)

    def proof_update(self, **values):
        self.proof.update(values)
        self.proof_path.write_text(json.dumps(self.proof))

    def test_recovers_once_and_retains_both_logs(self):
        result = self.execute()
        self.assertEqual(result['status'], 'passed', result)
        row = result['phases'][0]
        self.assertEqual(row['reason'], 'Passed after infrastructure recovery.')
        self.assertEqual(row['recovery']['status'], 'recovered')
        self.assertEqual([a['status'] for a in row['recovery']['attempts']], ['failed', 'passed'])
        for n, attempt in enumerate(row['recovery']['attempts'], 1):
            self.assertIn('attempt ' + str(n), (self.root / 'result' / attempt['log']).read_text())
        self.assertEqual((self.root / 'repair').read_text(), 'restart')
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_connection_loss_requests_reconnect(self):
        self.proof_update(state='disconnected')
        self.assertEqual(self.execute()['status'], 'passed')
        self.assertEqual((self.root / 'repair').read_text(), 'reconnect')

    def test_second_failure_does_not_repair_again_even_on_resume(self):
        self.code = self.code.replace('7 if n==1 else 0', '7')
        independent = Phase('independent', self.command('print("independent")'), str(self.root))
        result = self.execute(extra=(independent,))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['phases'][0]['recovery']['status'], 'exhausted')
        self.assertEqual(result['phases'][1]['status'], 'passed')
        self.assertEqual(self.execute(extra=(independent,), resume=True)['status'], 'failed')
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_healthy_environment_leaves_application_failure_alone(self):
        self.proof_update(state='ready')
        self.assertEqual(self.execute()['status'], 'failed')
        self.assertFalse((self.root / 'repair').exists())
        self.assertEqual((self.root / 'runs').read_text(), '1')

    def test_uncertain_worker_or_ownership_never_repairs(self):
        for values in ({'worker_stopped': False}, {'owned': False}, {'held': True},
                       {'exclusive': False}, {'target': 'other'}, {'state': 'unknown'}):
            with self.subTest(values=values), TemporaryDirectory() as directory:
                # Each scenario gets its own output and input evidence.
                old_root = self.root
                self.root = Path(directory)
                (self.root / 'proof.json').write_text(json.dumps(dict(self.proof, **values)))
                try:
                    self.assertEqual(self.execute()['status'], 'failed')
                    self.assertFalse((self.root / 'repair').exists())
                finally:
                    self.root = old_root

    def test_known_junit_failure_is_never_retried(self):
        report = self.root / 'tests.xml'
        report.write_text('<testsuite><testcase name="broken"><failure>assertion</failure></testcase></testsuite>')
        result = self.execute(self.phase(artifacts=(str(report),), artifact_types={str(report): 'junit'}))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['phases'][0]['recovery']['status'], 'not-safe')
        self.assertFalse((self.root / 'repair').exists())

    def test_changed_input_blocks_initial_execution(self):
        self.app.write_bytes(b'changed app')
        self.assertEqual(self.execute()['status'], 'failed')
        self.assertFalse((self.root / 'runs').exists())

    def test_changed_input_during_repair_blocks_replay(self):
        self.policy['recover'] = self.command(self.policy['recover'][-1] + "; Path('prepared.app').write_bytes(b'changed')")
        row = self.execute()['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('input changed', row['reason'])
        self.assertEqual((self.root / 'runs').read_text(), '1')

    def test_cancellation_at_recovery_admission_starts_no_repair(self):
        cancelled = Event()
        def event(value):
            if value.get('reason', '').startswith('Recovering test infrastructure'):
                cancelled.set()
        self.assertEqual(self.execute(event=event, cancelled=cancelled)['status'], 'cancelled')
        self.assertFalse((self.root / 'repair').exists())

    def test_probe_timeout_never_triggers_restart(self):
        self.policy.update(timeout=1, probe=self.command('import time; time.sleep(5)'))
        self.assertEqual(self.execute()['status'], 'failed')
        self.assertFalse((self.root / 'repair').exists())

    def test_interrupted_admission_is_not_replayed(self):
        result = self.execute()
        journal = self.root / 'result/infrastructure-recovery/native/recovery.json'
        data = json.loads(journal.read_text())
        data['state'] = 'admitted'
        data['result']['status'] = 'failed'
        data['result']['recovery']['status'] = 'recovering'
        journal.write_text(json.dumps(data))
        result['phases'][0]['status'] = 'running'
        result['phases'][0].pop('recovery', None)
        (self.root / 'result/result.json').write_text(json.dumps(result))
        row = self.execute(resume=True)['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('interrupted', row['reason'])
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_policy_validation_and_legacy_serialization(self):
        for options in ({'effect': 'deploy'}, {'effect': 'inherit'}, {'kind': 'setup'},
                        {'always': True}, {'resources': {}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.phase(**options)
        plan = Plan('fixture', 'test', {}, (self.phase(),), str(self.root))
        self.assertEqual(Plan.from_data(plan.data()).identity, plan.identity)
        with self.assertRaises(ValueError):
            replace(plan, capacities={'fixture:owned': 2})
        plain = replace(plan, phases=(replace(self.phase(), infrastructure_recovery={}),))
        self.assertNotIn('infrastructure_recovery', plain.data()['phases'][0])

    def test_failed_repair_or_readiness_prevents_second_test(self):
        for code in ('raise SystemExit(3)', 'print("no readiness change")'):
            with self.subTest(code=code), TemporaryDirectory() as directory:
                old_root = self.root
                self.root = Path(directory)
                (self.root / 'proof.json').write_text(json.dumps(self.proof))
                self.policy['recover'] = self.command(code)
                try:
                    row = self.execute()['phases'][0]
                    self.assertEqual(row['status'], 'failed')
                    self.assertEqual((self.root / 'runs').read_text(), '1')
                finally:
                    self.root = old_root

    def test_app_crash_classification_cannot_trigger_repair(self):
        self.proof_update(failure_kind='app-crash')
        self.assertEqual(self.execute()['status'], 'failed')
        self.assertFalse((self.root / 'repair').exists())

    def test_timeout_requires_positive_environment_failure_evidence(self):
        self.code = "import time; from pathlib import Path; p=Path('runs'); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); time.sleep(5 if n==1 else 0)"
        result = self.execute(self.phase(timeout=.3))
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['phases'][0]['recovery']['attempts'][0]['status'], 'timeout')

    def test_stale_junit_is_not_accepted_after_recovery(self):
        report = self.root / 'tests.xml'
        report.write_text('<testsuite><testcase name="previous-pass"/></testsuite>')
        row = self.execute(self.phase(artifacts=(str(report),), artifact_types={str(report): 'junit'}))['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('fresh declared output', row['error'])
        paths = [Path(a['artifacts'][0]['path']) for a in row['recovery']['attempts']]
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(path.is_file() for path in paths))

    def test_recovered_pass_is_not_cached_as_clean_evidence(self):
        row = self.execute(self.phase(reuse_key='a' * 64))['phases'][0]
        self.assertEqual(row['status'], 'passed')
        self.assertFalse((self.root / 'cache' / ('a' * 64 + '.json')).exists())

    def test_no_policy_preserves_single_execution(self):
        row = self.execute(self.phase(infrastructure_recovery={}))['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertNotIn('recovery', row)
        self.assertFalse((self.root / 'repair').exists())

    def test_target_budget_is_shared_across_test_phases(self):
        self.code = "import json; from pathlib import Path; p=Path('proof.json'); d=json.loads(p.read_text()); d['state']='stopped'; p.write_text(json.dumps(d)); " + self.code.replace('7 if n==1 else 0', '7')
        result = self.execute(extra=(replace(self.phase(), id='next-test'),))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['phases'][1]['status'], 'skipped')
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_later_target_failure_cannot_gain_another_recovery(self):
        initial = self.phase()
        later = replace(initial, id='later', argv=self.command(
            "import json; from pathlib import Path; p=Path('proof.json'); d=json.loads(p.read_text()); d['state']='stopped'; p.write_text(json.dumps(d)); raise SystemExit(7)"))
        result = self.execute(initial, extra=(later, replace(later, id='last')))
        self.assertEqual([row['status'] for row in result['phases']], ['passed', 'failed', 'skipped'])
        self.assertIn('already used', result['phases'][1]['reason'])

    def test_streamed_crash_cannot_be_erased_by_passing_junit(self):
        report = self.root / 'tests.xml'
        event = dict(schema=1, kind='test_finished', name='app', classname='native',
                     file='app.py', status='crashed', message='App terminated')
        self.code = ("from pathlib import Path; print(" + repr('@@BUILD_MANAGER_TEST@@' + json.dumps(event)) + "); "
                     "Path('tests.xml').write_text('<testsuite><testcase name=\"other\"/></testsuite>'); raise SystemExit(7)")
        row = self.execute(self.phase(artifacts=(str(report),), artifact_types={str(report): 'junit'}))['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['recovery']['status'], 'not-safe')
        self.assertFalse((self.root / 'repair').exists())
        self.assertEqual(row['observed_test_failures'][0]['status'], 'crashed')

    def test_completed_journal_reconciles_interrupted_budget_publication(self):
        cancelled = Event()
        def event(value):
            if value.get('id') == 'native' and value.get('status') == 'passed':
                cancelled.set()
        later = replace(self.phase(), id='later')
        self.execute(extra=(later,), event=event, cancelled=cancelled)
        budget = next((self.root / 'result/infrastructure-recovery/targets').glob('*.json'))
        data = json.loads(budget.read_text())
        data['status'] = 'admitted'
        budget.write_text(json.dumps(data))
        result = self.execute(extra=(later,), resume=True)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual((self.root / 'runs').read_text(), '3')

    def test_malformed_journal_fails_phase_without_crashing_workflow(self):
        result = self.execute()
        journal = self.root / 'result/infrastructure-recovery/native/recovery.json'
        journal.write_text('{}')
        result['phases'][0]['status'] = 'running'
        result['phases'][0].pop('recovery', None)
        (self.root / 'result/result.json').write_text(json.dumps(result))
        resumed = self.execute(resume=True)
        self.assertEqual(resumed['status'], 'failed')
        self.assertIn('recovery record', resumed['phases'][0]['error'])
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_input_output_alias_is_rejected(self):
        alias = self.root / 'alias.app'
        alias.hardlink_to(self.app)
        with self.assertRaisesRegex(ValueError, 'inputs'):
            self.phase(artifacts=(str(alias),))

    def test_live_logs_resolve_and_attempts_do_not_share_test_facts(self):
        from build_manager.run_state import RunState
        state = RunState()
        paths = []
        def event(value):
            if value['type'] == 'phase':
                state.update(value)
                if value.get('log'):
                    paths.append(self.root / 'result' / value['log'])
        progress = dict(schema=1, kind='test_finished', name='first-only', classname='native',
                        file='app.py', status='passed')
        self.code = self.code.replace("raise SystemExit", "print(" + repr('@@BUILD_MANAGER_TEST@@' + json.dumps(progress))
                                      + ") if n==1 else None; raise SystemExit")
        self.assertEqual(self.execute(event=event)['status'], 'passed')
        self.assertTrue(paths)
        self.assertTrue(all(path.is_file() for path in paths), paths)
        self.assertEqual(state.facts['native']['live_tests'], [])

    def test_damaged_budget_is_rejected_before_execution(self):
        self.execute()
        budget = next((self.root / 'result/infrastructure-recovery/targets').glob('*.json'))
        budget.write_text('[]')
        # Exercise a new phase directly against the same retained target state.
        from build_manager.infrastructure_recovery import execute
        with self.assertRaisesRegex(ValueError, 'recovery record'):
            execute(replace(self.phase(), id='later'), self.root / 'result',
                    lambda *_: self.fail('must not execute'), cancelled=lambda: False, event=lambda _: None)

    def test_recovered_pass_cannot_hide_a_streamed_test_failure(self):
        progress = dict(schema=1, kind='test_finished', name='app', status='failed', message='assertion')
        self.code = self.code.replace('raise SystemExit', 'print(' + repr('@@BUILD_MANAGER_TEST@@' + json.dumps(progress))
                                      + ') if n==2 else None; raise SystemExit')
        row = self.execute()['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['recovery']['status'], 'exhausted')
        self.assertIn('successful exit', row['error'])

    def test_restoring_completed_recovery_rechecks_prepared_inputs(self):
        result = self.execute()
        result['phases'][0]['status'] = 'running'
        result['phases'][0].pop('recovery', None)
        (self.root / 'result/result.json').write_text(json.dumps(result))
        self.app.write_bytes(b'changed app')
        row = self.execute(resume=True)['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('input changed', row['error'])
        self.assertEqual((self.root / 'runs').read_text(), '2')

    def test_cancelling_restored_input_verification_does_not_escape_supervisor(self):
        from unittest.mock import patch
        from build_manager.infrastructure_recovery import _read_journal
        result = self.execute()
        result['phases'][0]['status'] = 'running'
        result['phases'][0].pop('recovery', None)
        (self.root / 'result/result.json').write_text(json.dumps(result))
        cancelled = Event()
        def read(*args):
            saved = _read_journal(*args)
            cancelled.set()
            return saved
        with patch('build_manager.infrastructure_recovery._read_journal', side_effect=read):
            resumed = self.execute(resume=True, cancelled=cancelled)
        self.assertEqual(resumed['status'], 'cancelled')
        self.assertEqual(resumed['phases'][0]['status'], 'cancelled')
        self.assertEqual((self.root / 'runs').read_text(), '2')


if __name__ == '__main__':
    unittest.main()
