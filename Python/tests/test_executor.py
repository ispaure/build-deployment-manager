"""Real harmless child processes prove the generic second-project boundary."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Timer
import unittest

from build_manager import Executor, Phase, Plan
from build_manager.locking import workspace_lock
from build_manager.profiles import effective, load_profile, save_profile


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='second-project-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def phase(self, name, code, **options):
        return Phase(name, (sys.executable, '-c', code), str(self.root), **options)

    def plan(self, *phases, **options):
        return Plan('Different harmless project', 'contract', {'revision': 'synthetic-v1'},
                    phases, str(self.root / 'workspace'), **options)

    def run_plan(self, plan, **options):
        return Executor(**options).run(plan, self.root / 'result')

    def test_second_project_runs_without_importing_logistics_or_cloud_credentials(self):
        plan = self.plan(self.phase('hello', 'print("second project completed")'))
        plan.save(self.root / 'plan.json')
        result = self.run_plan(Plan.load(self.root / 'plan.json'))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['source'], {'revision': 'synthetic-v1'})
        self.assertEqual((self.root / 'result/hello.log').read_text(), 'second project completed\n')
        self.assertNotIn('mobile.app', sys.modules)
        self.assertNotIn('features.application', sys.modules)

    def test_literal_arguments_and_unicode_working_directory_survive_transport(self):
        folder = self.root / 'space café & literal'
        folder.mkdir()
        arguments = ['space value', 'quote"value', 'literal&echo', 'trailing\\', 'café']
        phase = Phase('quoted', (sys.executable, '-c',
            'import json,sys;print(json.dumps(sys.argv[1:]))', *arguments), str(folder))
        result = self.run_plan(self.plan(phase))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(json.loads((self.root / 'result/quoted.log').read_text()), arguments)

    def test_failure_blocks_dependents_but_runs_independent_and_cleanup_phases(self):
        result = self.run_plan(self.plan(self.phase('failed', 'raise SystemExit(4)'),
            self.phase('dependent', 'raise AssertionError("must not run")', dependencies=('failed',)),
            self.phase('independent', 'print("still useful")'),
            self.phase('cleanup', 'print("cleaned")', dependencies=('dependent',), always=True)))
        self.assertEqual([row['status'] for row in result['phases']], ['failed', 'skipped', 'passed', 'passed'])
        self.assertEqual(result['status'], 'failed')

    def test_timeout_terminates_real_child_and_still_writes_result(self):
        result = self.run_plan(self.plan(self.phase('stalled', 'import time; time.sleep(30)', timeout=.1)))
        self.assertEqual(result['phases'][0]['status'], 'timeout')
        self.assertEqual(json.loads((self.root / 'result/result.json').read_text())['status'], 'failed')
        self.assertLess(result['seconds'], 8)

    def test_temporary_inspection_releases_worker_and_reuses_completed_build(self):
        code = "from pathlib import Path; p=Path('ready'); print('checking'); raise SystemExit(0 if p.exists() else 75)"
        plan = self.plan(
            self.phase('build', "from pathlib import Path; Path('build-count').write_text('once')"),
            self.phase('availability', code, effect='inspect', dependencies=('build',),
                       retry_exit_codes=(75,), retry_delay=.2),
            self.phase('independent', "from pathlib import Path; Path('ready').touch()"),
            self.phase('consumer', "print('ready')", dependencies=('availability',)))
        report = self.run_plan(plan)
        self.assertEqual(report['status'], 'passed')
        ready = next(row for row in report['phases'] if row['id'] == 'availability')
        self.assertGreaterEqual(ready['retry_count'], 1)
        self.assertTrue((self.root / 'result' / ready['retry_attempts'][0]['log']).is_file())
        self.assertEqual((self.root / 'build-count').read_text(), 'once')

    def test_indefinite_inspection_wait_is_cancellable_and_not_an_unknown_effect(self):
        cancelled = Event()
        def event(row):
            if row.get('status') == 'retrying': cancelled.set()
        plan = self.plan(self.phase('offline', 'raise SystemExit(75)', effect='inspect',
                                    retry_exit_codes=(75,), retry_delay=30),
                         self.phase('cleanup', 'pass', always=True))
        report = self.run_plan(plan, cancelled=cancelled, event=event)
        self.assertEqual(report['status'], 'cancelled')
        self.assertEqual(report['phases'][-1]['status'], 'passed')
        self.assertLess(report['seconds'], 5)

    def test_retry_policy_rejects_external_effects_and_preserves_nontransient_failures(self):
        for effect in ('deploy', 'upload', 'publish', 'inherit'):
            with self.subTest(effect=effect), self.assertRaises(ValueError):
                self.phase('unsafe', 'pass', effect=effect, retry_exit_codes=(75,))
        report = self.run_plan(self.plan(self.phase('bad-config', 'raise SystemExit(1)',
            effect='inspect', retry_exit_codes=(75,), retry_delay=.1)))
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn('retry_count', report['phases'][0])

    def test_cancellation_stops_current_work_and_never_starts_remaining_device(self):
        cancelled = Event()
        timer = Timer(.15, cancelled.set)
        self.addCleanup(timer.cancel)
        def started(event):
            if event.get('id') == 'first-device' and event.get('status') == 'running':
                timer.start()
        result = self.run_plan(self.plan(self.phase('first-device', 'import time; time.sleep(30)'),
            self.phase('next-device', 'raise AssertionError("must not start")'),
            self.phase('cleanup', 'print("owned fixtures only")', always=True)), cancelled=cancelled, event=started)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual([row['status'] for row in result['phases']], ['cancelled', 'skipped', 'passed'])

    def test_unconfirmed_side_effect_does_not_launch_process(self):
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.run_plan(self.plan(self.phase('upload', 'raise AssertionError("never")'), effect='upload'))
        self.assertFalse((self.root / 'result').exists())

    def test_workspace_lock_prevents_concurrent_writer(self):
        with workspace_lock(self.root / 'lock'):
            with self.assertRaisesRegex(RuntimeError, 'Another operation'):
                with workspace_lock(self.root / 'lock'):
                    self.fail('two writers admitted')

    def test_secrets_and_multiline_keys_do_not_reach_logs_or_failure_summary(self):
        from unittest.mock import patch
        code = 'import os; print("token="+os.environ["GH_TOKEN"]); print("-----BEGIN "+"PRIVATE KEY-----"); print(os.environ["SYNTHETIC_PEM_BODY"]); print("-----END "+"PRIVATE KEY-----"); raise SystemExit(1)'
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-secret', 'SYNTHETIC_PEM_BODY': 'privatebytes'}):
            result = self.run_plan(self.plan(self.phase('provider', code)))
        outputs = ''.join(p.read_text() for p in (self.root / 'result').glob('*') if p.is_file())
        self.assertNotIn('synthetic-secret', outputs)
        self.assertNotIn('privatebytes', outputs)
        self.assertEqual(result['status'], 'failed')

    def test_invalid_dependency_and_unsafe_log_name_fail_before_execution(self):
        with self.assertRaises(ValueError):
            self.plan(self.phase('a', 'pass', dependencies=('missing',)))
        with self.assertRaises(ValueError):
            self.phase('../escape', 'pass')

    def test_expected_artifact_is_captured_and_missing_artifact_fails(self):
        artifact = self.root / 'prepared.json'
        code = f'from pathlib import Path; Path({str(artifact)!r}).write_text("verified version 7")'
        result = self.run_plan(self.plan(self.phase('prepare', code, artifacts=(str(artifact),))))
        recorded = result['phases'][0]['artifacts'][0]
        captured = Path(recorded['path'])
        self.assertEqual(captured.read_text(), 'verified version 7')
        artifact.write_text('new settings must not relabel old result')
        self.assertEqual(captured.read_text(), 'verified version 7')
        missing = Executor().run(self.plan(self.phase('prepare', 'pass', artifacts=(str(self.root / 'missing'),))),
                                 self.root / 'missing-result')
        self.assertEqual(missing['status'], 'failed')
        self.assertIn('Expected prepared artifact', missing['phases'][0]['error'])

    def test_cancellation_during_artifact_hash_still_records_result_and_runs_cleanup(self):
        from unittest.mock import patch
        from commonUtils.runtime.streams import file_sha256
        cancelled = Event()
        artifact, cleaned = self.root / 'artifact.bin', self.root / 'cleaned'
        prepare = self.phase('prepare', f'from pathlib import Path; Path({str(artifact)!r}).write_bytes(b"output")',
                             artifacts=(str(artifact),))
        cleanup = self.phase('cleanup', f'from pathlib import Path; Path({str(cleaned)!r}).touch()', always=True)
        def cancel_hash(path, **options):
            cancelled.set()
            return file_sha256(path, **options)
        with patch('build_manager.executor.file_sha256', side_effect=cancel_hash):
            result = self.run_plan(self.plan(prepare, cleanup), cancelled=cancelled)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['phases'][0]['status'], 'cancelled')
        self.assertEqual(result['phases'][1]['status'], 'passed')
        self.assertTrue(cleaned.exists())
        self.assertEqual(json.loads((self.root / 'result/result.json').read_text())['status'], 'cancelled')

    def test_workspace_conflict_is_a_structured_failure(self):
        plan = self.plan(self.phase('blocked', 'raise AssertionError("never")'))
        with workspace_lock(self.root / 'workspace/operation.lock'):
            result = self.run_plan(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Another operation', result['error'])

    def test_timeout_closes_pipe_held_by_descendant_after_parent_exits(self):
        code = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])'
        result = self.run_plan(self.plan(self.phase('orphan', code, timeout=.15)))
        self.assertEqual(result['phases'][0]['status'], 'timeout')
        self.assertLess(result['seconds'], 5)


    @unittest.skipIf(os.name == 'nt', 'POSIX process group contract')
    def test_orphan_ignoring_sigterm_is_killed_after_parent_exit(self):
        import signal
        import time
        from unittest.mock import patch
        import build_manager.executor as module
        child = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'
        code = 'import subprocess,sys; p=subprocess.Popen([sys.executable,"-c",'+repr(child)+'],stdout=subprocess.PIPE); print(p.stdout.readline().decode(),flush=True)'
        original = module.subprocess.Popen
        processes = []
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        def rescue():
            for process in processes:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        timer = Timer(3, rescue)
        timer.start()
        try:
            with patch.object(module.subprocess, 'Popen', side_effect=spawn):
                started = time.monotonic()
                result = self.run_plan(self.plan(self.phase('orphan', code, timeout=.2)))
            self.assertEqual(result['phases'][0]['status'], 'timeout')
            self.assertLess(time.monotonic()-started, 2)
        finally:
            timer.cancel()
            rescue()


    def test_cleanup_permission_error_remains_a_structured_failed_phase(self):
        from unittest.mock import patch
        with patch('build_manager.executor.stop_process',side_effect=PermissionError('synthetic persistent cleanup denial')):
            result = self.run_plan(self.plan(self.phase('completed', 'print("finished")')))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['phases']), 1)
        self.assertIn('cleanup denial', result['phases'][0]['cleanup_error'])


    def test_cancelled_operation_still_reports_failed_required_cleanup(self):
        cancelled=Event();cancelled.set()
        result=self.run_plan(self.plan(self.phase('work','pass'),
            self.phase('cleanup','raise SystemExit(3)',always=True)),cancelled=cancelled)
        self.assertEqual([row['status'] for row in result['phases']],['skipped','failed'])
        self.assertEqual(result['status'],'failed')


class ProfileTests(unittest.TestCase):
    def test_precedence_preserves_effective_value_provenance(self):
        values, sources = effective({'group': 'default', 'tool': 'python'}, {'group': 'profile'},
            {'GROUP': 'environment'}, {'group': 'once'}, variables={'group': 'GROUP'})
        self.assertEqual(values, {'group': 'once', 'tool': 'python'})
        self.assertEqual(sources, {'group': 'run override', 'tool': 'repository default'})

    def test_profile_persists_references_and_rejects_secret_contents(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            save_profile(path, {'key_reference': 'protected/file.p8'}, allowed={'key_reference'})
            self.assertEqual(load_profile(path), {'key_reference': 'protected/file.p8'})
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                save_profile(path, {'private_key': 'secret'}, allowed={'private_key'})

    def test_build_reservation_handles_existing_explicit_and_duplicate_values(self):
        from build_manager.versions import next_number, reserve_number
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'numbers.json'
            self.assertEqual(next_number(path, existing=[4], minimum=3), 5)
            self.assertFalse(path.exists())
            self.assertEqual(reserve_number(path, existing=[4], minimum=3, maximum=20), 5)
            self.assertEqual(reserve_number(path, maximum=20, override='8'), 8)
            with self.assertRaises(ValueError):
                reserve_number(path, maximum=20, override='8')
            with self.assertRaises(ValueError):
                reserve_number(path, maximum=8)

    def test_invalid_boolean_profile_and_build_history_are_actionable(self):
        from build_manager.versions import next_number
        with self.assertRaisesRegex(ValueError, 'bool'):
            effective({'shutdown': False}, {'shutdown': 'false'})
        with TemporaryDirectory() as directory:
            path = Path(directory)/'counter.json'
            path.write_text('{"last": "4"}')
            with self.assertRaisesRegex(ValueError, 'integer'):
                next_number(path)
            path.write_text('[]')
            with self.assertRaisesRegex(ValueError, 'schema'):
                next_number(path)
            with self.assertRaisesRegex(ValueError, 'schema'):
                load_profile(path)

    def test_secret_values_cannot_be_written_into_serialized_phase_environment(self):
        with self.assertRaisesRegex(ValueError,'inherited'):
            Plan('Fixture','test',{},(Phase('example',('python','--version'),'.',
                 environment={'CUSTOM_API_SECRET':'synthetic-secret'}),),'.',
                 secret_environment=('CUSTOM_API_SECRET',))
