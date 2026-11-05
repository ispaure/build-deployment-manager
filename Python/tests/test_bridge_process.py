"""Owned session subgroups cannot mutate after bridge cancellation or early exit."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from build_manager import bridge_process


@unittest.skipIf(os.name == 'nt', 'Real POSIX session/subgroup ownership')
class BridgeSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.owners = []
        self.addCleanup(self.retire_owners)

    def retire_owners(self):
        for process in self.owners:
            with patch.object(bridge_process, 'STOP_GRACE', .1):
                bridge_process.stop_session(process)

    def scripts(self, *, early_exit=False, ignore_term=False):
        # Two different descendant PGIDs stay in the exact bridge SID. Both
        # inherit a lease fd and stdout/stderr, reproducing installer descendants.
        (self.root / 'mutator.py').write_text('''import os,signal,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);role=sys.argv[2];descriptor=int(sys.argv[3])
if sys.argv[4]=='ignore': signal.signal(signal.SIGTERM,signal.SIG_IGN)
if role=='child':
    subprocess.Popen([sys.executable,str(root/'mutator.py'),str(root),'grandchild',str(descriptor),sys.argv[4]],process_group=0,pass_fds=(descriptor,))
(root/(role+'.mutation')).write_text('0')
(root/(role+'.ready')).write_text(str(os.getpid()))
counter=0
while True:
    (root/(role+'.mutation')).write_text(str(counter));counter+=1;time.sleep(.02)
''')
        (self.root / 'bridge.py').write_text('''import fcntl,json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]);lease=open(root/'environment.lock','w');fcntl.flock(lease,fcntl.LOCK_EX)
subprocess.Popen([sys.executable,str(root/'mutator.py'),str(root),'child',str(lease.fileno()),sys.argv[3]],process_group=0,pass_fds=(lease.fileno(),))
deadline=time.monotonic()+5
while not (root/'grandchild.ready').exists():
    if time.monotonic()>deadline: raise RuntimeError('descendant startup failed')
    time.sleep(.01)
if sys.argv[2]=='exit':
    print(json.dumps(dict(schema=1,result='ready')),flush=True)
else:
    time.sleep(30)
''')
        return [sys.executable, str(self.root / 'bridge.py'), str(self.root),
                'exit' if early_exit else 'wait', 'ignore' if ignore_term else 'normal']

    def assert_retired(self):
        import fcntl
        before = {role: (self.root / (role + '.mutation')).read_bytes() for role in ('child', 'grandchild')}
        time.sleep(.2)
        self.assertEqual(before, {role: (self.root / (role + '.mutation')).read_bytes() for role in before})
        with (self.root / 'environment.lock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def invoke(self, argv, *, cancelled=lambda: False, timeout=5):
        spawn = subprocess.Popen
        def capture(command, **options):
            process = spawn(command, **options)
            if options.get('start_new_session'): self.owners.append(process)
            return process
        with patch.object(bridge_process.subprocess, 'Popen', side_effect=capture):
            return bridge_process.run(argv, '{}', cwd=self.root, env=dict(os.environ),
                                      timeout=timeout, cancelled=cancelled)

    def test_cancel_waits_for_child_grandchild_and_inherited_lease(self):
        argv = self.scripts()
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.invoke(argv, cancelled=lambda: (self.root / 'grandchild.ready').exists())
        self.assert_retired()

    def test_timeout_retires_descendant_subgroups_before_returning(self):
        argv = self.scripts()
        with self.assertRaisesRegex(ValueError, 'timed out'):
            self.invoke(argv, timeout=.5)
        self.assert_retired()

    def test_early_bridge_exit_does_not_wait_on_descendant_pipe_writers(self):
        argv = self.scripts(early_exit=True)
        started = time.monotonic()
        result = self.invoke(argv, timeout=5)
        self.assertEqual(json.loads(result.stdout)['result'], 'ready')
        self.assertLess(time.monotonic() - started, 4)
        self.assert_retired()

    def test_force_kill_is_bounded_and_does_not_touch_another_session(self):
        argv = self.scripts(ignore_term=True)
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'], start_new_session=True)
        def retire_sentinel():
            # Inventory this exact fixture-owned SID, including any descendants.
            # addCleanup preserves a body failure separately from cleanup errors.
            bridge_process.stop_session(sentinel)
            self.assertIsNotNone(sentinel.returncode)
            self.assertEqual(bridge_process.session_groups(sentinel.pid), {})
        self.addCleanup(retire_sentinel)
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.invoke(argv, cancelled=lambda: (self.root / 'grandchild.ready').exists())
        self.assertLess(time.monotonic() - started, bridge_process.STOP_GRACE + 8)
        self.assertIsNone(sentinel.poll())
        self.assert_retired()

    def test_clean_completion_reaps_root_and_closes_all_protocol_pipes(self):
        spawn = subprocess.Popen; owners = []
        def capture(argv, **options):
            process = spawn(argv, **options)
            if options.get('start_new_session'): owners.append(process)
            return process
        with patch.object(bridge_process.subprocess, 'Popen', side_effect=capture):
            result = self.invoke([sys.executable, '-c', 'import sys;print(sys.stdin.read())'])
        self.assertEqual(result.stdout.strip(), '{}')
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].poll(), 0)
        self.assertTrue(all(stream.closed for stream in (owners[0].stdin, owners[0].stdout, owners[0].stderr)))


class BridgeInventoryRetryTests(unittest.TestCase):
    def test_transient_timeout_reads_fresh_inventory_without_repeating_request(self):
        timeout = subprocess.TimeoutExpired('ps', 1)
        with patch.object(bridge_process.time, 'monotonic', return_value=0), \
                patch.object(bridge_process, 'session_groups', side_effect=[timeout, {70: [12]}]) as inventory:
            self.assertEqual(bridge_process.teardown_inventory(41, deadline=5), {70: [12]})
        self.assertEqual(inventory.call_count, 2)
        self.assertEqual(inventory.call_args_list[0].kwargs, dict(timeout=1))

    def test_permanent_timeout_preserves_first_cause_and_limits_attempts(self):
        original = subprocess.TimeoutExpired('ps', 1)
        with patch.object(bridge_process.time, 'monotonic', return_value=0), \
                patch.object(bridge_process, 'session_groups', side_effect=[original, subprocess.TimeoutExpired('ps', 1)]) as inventory:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                bridge_process.teardown_inventory(41, deadline=5)
        self.assertIs(caught.exception, original)
        self.assertEqual(inventory.call_count, 2)

    def test_expired_budget_prevents_second_attempt_and_preserves_original(self):
        original = subprocess.TimeoutExpired('ps', .25)
        with patch.object(bridge_process.time, 'monotonic', side_effect=[.75, 1]), \
                patch.object(bridge_process, 'session_groups', side_effect=original) as inventory:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                bridge_process.teardown_inventory(41, deadline=1)
        self.assertIs(caught.exception, original)
        inventory.assert_called_once_with(41, timeout=.25)

    def test_expired_budget_never_starts_inventory(self):
        with patch.object(bridge_process.time, 'monotonic', return_value=1), \
                patch.object(bridge_process, 'session_groups') as inventory:
            with self.assertRaises(subprocess.TimeoutExpired):
                bridge_process.teardown_inventory(41, deadline=1)
        inventory.assert_not_called()

    def test_non_timeout_failures_are_not_retried(self):
        for original in (OSError('missing or malformed ps'), PermissionError('denied')):
            with self.subTest(error=type(original).__name__), \
                    patch.object(bridge_process.time, 'monotonic', return_value=0), \
                    patch.object(bridge_process, 'session_groups', side_effect=original) as inventory:
                with self.assertRaises(type(original)) as caught:
                    bridge_process.teardown_inventory(41, deadline=5)
                self.assertIs(caught.exception, original)
                inventory.assert_called_once()

    def test_inventory_subprocess_receives_remaining_budget(self):
        with patch.object(bridge_process.Path, 'is_file', return_value=True), \
                patch.object(bridge_process.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')) as run:
            self.assertEqual(bridge_process.session_groups(41, timeout=.125), {})
        self.assertEqual(run.call_args.kwargs['timeout'], .125)

    def test_retry_never_signals_last_inventory_as_if_it_were_fresh(self):
        process = Mock(pid=41, returncode=0)
        sequence = [{70: [12]}, subprocess.TimeoutExpired('ps', 1), {80: [13]}, {}]
        with patch.object(bridge_process, 'session_groups', side_effect=sequence), \
                patch.object(bridge_process, 'signal_session') as signal_owned, \
                patch.object(bridge_process.time, 'sleep'), \
                patch.object(bridge_process, 'stop_process') as fallback:
            bridge_process.stop_session(process)
        self.assertEqual([call.args for call in signal_owned.call_args_list],
                         [(41, {70: [12]}, signal.SIGTERM), (41, {80: [13]}, signal.SIGTERM)])
        fallback.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    def test_permanent_timeout_retains_last_inventory_without_resignalling_it(self):
        process = Mock(pid=41, returncode=-15)
        original = subprocess.TimeoutExpired('ps', 1)
        with patch.object(bridge_process, 'session_groups', side_effect=[{70: [12]}, original, original]), \
                patch.object(bridge_process, 'signal_session') as signal_owned, \
                patch.object(bridge_process.time, 'sleep'), \
                patch.object(bridge_process, 'stop_process') as fallback:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                bridge_process.stop_session(process)
        self.assertIs(caught.exception, original)
        signal_owned.assert_called_once_with(41, {70: [12]}, signal.SIGTERM)
        receipt = original._owned_bridge_receipt
        self.assertEqual(receipt['stage'], 'session_inventory')
        self.assertEqual(receipt['last_verified_owned_processes'], [dict(pid=12, pgid=70)])
        self.assertFalse(receipt['session_verified_empty'])
        self.assertFalse(receipt['retry_safe'])
        fallback.assert_called_once_with(process, grace=15)

    def test_short_term_grace_does_not_reset_additional_retirement_budget(self):
        process = Mock(pid=41, returncode=-15)
        clock = [0]
        signals = SimpleNamespace(SIGTERM=15, SIGKILL=9)
        def inventory(_session, *, deadline):
            self.assertAlmostEqual(deadline, 5.1)
            if clock[0] == 0:
                clock[0] = .2
                return {70: [12]}
            raise subprocess.TimeoutExpired('ps', deadline - clock[0])
        with patch.object(bridge_process, 'signal', signals), \
                patch.object(bridge_process, 'STOP_GRACE', .1), \
                patch.object(bridge_process.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(bridge_process.time, 'sleep'), \
                patch.object(bridge_process, 'teardown_inventory', side_effect=inventory) as read, \
                patch.object(bridge_process, 'signal_session') as signal_owned, \
                patch.object(bridge_process, 'stop_process'):
            with self.assertRaises(subprocess.TimeoutExpired): bridge_process.stop_session(process)
        self.assertEqual(read.call_count, 2)
        self.assertEqual([call.args[2] for call in signal_owned.call_args_list], [signals.SIGTERM, signals.SIGKILL])

    def test_deadline_contract_does_not_require_host_sigkill(self):
        result = unittest.TestResult()
        # Windows has SIGTERM but no SIGKILL. This portable deadline contract
        # owns its simulated signals and never calls an actual host signal API.
        with patch.object(bridge_process, 'signal', SimpleNamespace(SIGTERM=15)), \
                patch.dict(globals(), signal=SimpleNamespace(SIGTERM=15)):
            type(self)('test_short_term_grace_does_not_reset_additional_retirement_budget').run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(result.skipped, [])


class BridgeOwnershipUnitTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX host prerequisite')
    def test_missing_host_inventory_prevents_any_adapter_launch(self):
        with patch.object(bridge_process, 'session_groups', side_effect=OSError('missing ps')), \
                patch.object(bridge_process.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'host ps utility'):
                bridge_process.run(['project-python', 'bridge.py'], '{}', cwd='.', env={},
                                   timeout=1, cancelled=lambda: False)
            launch.assert_not_called()
    def windows_accounting(self, values):
        from build_manager.windows_process import WindowsProcess
        process = object.__new__(WindowsProcess)
        process._job = object(); process.args = ['owned-bridge']
        sequence = iter(values)
        def query(job, kind, output, size, returned):
            self.assertIs(job, process._job); self.assertEqual(kind, 1)
            output._obj.active_processes = next(sequence, values[-1])
            return 1
        process.kernel = SimpleNamespace(QueryInformationJobObject=Mock(side_effect=query))
        return process

    def test_windows_accounting_waits_until_all_job_members_retire(self):
        process = self.windows_accounting([2, 1, 0]); process.wait_tree(timeout=.5)
        self.assertEqual(process.kernel.QueryInformationJobObject.call_count, 3)

    def test_windows_accounting_timeout_is_bounded(self):
        process = self.windows_accounting([1]); started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired): process.wait_tree(timeout=.03)
        self.assertLess(time.monotonic() - started, .5)

    def test_closed_windows_job_never_queries_the_embedding_application_job(self):
        process = self.windows_accounting([0]); process._job = None
        with self.assertRaisesRegex(RuntimeError, 'job is closed'): process.wait_tree()
        process.kernel.QueryInformationJobObject.assert_not_called()

    def test_inventory_failure_is_not_successful_cancellation(self):
        process = Mock()
        with patch.object(bridge_process, 'session_groups', side_effect=OSError('inventory unavailable')), \
                patch.object(bridge_process, 'stop_process') as stop:
            with self.assertRaises(OSError): bridge_process.stop_session(process)
        stop.assert_called_once_with(process, grace=15)

    def test_inventory_failure_preserves_original_cause_if_root_fallback_also_fails(self):
        process = Mock(pid=41, returncode=0)
        original = OSError('private inventory detail')
        with patch.object(bridge_process, 'session_groups', side_effect=original), \
                patch.object(bridge_process, 'stop_process', side_effect=PermissionError('private fallback detail')):
            with self.assertRaises(OSError) as caught:
                bridge_process.stop_session(process)
        self.assertIs(caught.exception, original)
        failure = bridge_process.teardown_failure(process, 'session_teardown', original)
        self.assertEqual(failure.receipt['stage'], 'session_inventory')
        self.assertEqual(failure.receipt['session_id'], 41)
        self.assertEqual(failure.receipt['error_class'], 'OSError')
        self.assertEqual(failure.receipt['fallback_error_class'], 'PermissionError')
        self.assertFalse(failure.receipt['retry_safe'])
        self.assertEqual(failure.receipt['ownership'], 'incomplete')
        self.assertNotIn('private', str(failure))

    def test_signal_failure_receipt_contains_only_bounded_last_verified_owned_members(self):
        process = Mock(pid=41, returncode=None)
        groups = {70: list(range(100, 140))}
        with patch.object(bridge_process, 'session_groups', return_value=groups), \
                patch.object(bridge_process, 'signal_session', side_effect=PermissionError('private')), \
                patch.object(bridge_process, 'stop_process'):
            with self.assertRaises(OSError) as caught:
                bridge_process.stop_session(process)
        failure = bridge_process.teardown_failure(process, 'session_teardown', caught.exception)
        self.assertEqual(failure.receipt['stage'], 'session_sigterm')
        self.assertEqual(failure.receipt['owned_process_count'], 40)
        self.assertEqual(len(failure.receipt['last_verified_owned_processes']), 32)
        self.assertTrue(failure.receipt['truncated'])
        self.assertEqual(failure.receipt['last_verified_owned_processes'][0], dict(pid=100, pgid=70))
        self.assertFalse(failure.receipt['session_verified_empty'])
        self.assertNotIn('private', str(failure))

    def test_root_reap_failure_is_identified_without_exposing_process_arguments(self):
        process = Mock(pid=41, returncode=0)
        process.wait.side_effect = subprocess.TimeoutExpired(['private-command'], 5)
        with patch.object(bridge_process, 'session_groups', return_value={}), \
                patch.object(bridge_process, 'stop_process'):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                bridge_process.stop_session(process)
        failure = bridge_process.teardown_failure(process, 'session_teardown', caught.exception)
        self.assertEqual(failure.receipt['stage'], 'root_reap')
        self.assertNotIn('private-command', str(failure))
        self.assertFalse(failure.receipt['retry_safe'])

    @unittest.skipIf(os.name == 'nt', 'POSIX teardown receipt')
    def test_pipe_drain_failure_exposes_owned_receipt_and_closes_streams(self):
        process = Mock(pid=41, returncode=0)
        process.stdin, process.stdout, process.stderr = [io.StringIO() for _ in range(3)]
        process.communicate.side_effect = [('response', ''), subprocess.TimeoutExpired(['private-command'], 3)]
        with patch.object(bridge_process, 'session_groups', return_value={}), \
                patch.object(bridge_process.subprocess, 'Popen', return_value=process), \
                patch.object(bridge_process, 'stop_session'):
            with self.assertRaises(ValueError) as caught:
                bridge_process.run(['private-command'], 'private payload', cwd='.', env={'TOKEN': 'private'},
                                   timeout=10, cancelled=lambda: False)
        receipt = caught.exception.receipt
        self.assertEqual(receipt['stage'], 'pipe_drain')
        self.assertTrue(receipt['session_verified_empty'])
        self.assertFalse(receipt['retry_safe'])
        self.assertEqual(receipt['session_id'], 41)
        self.assertNotIn('private', str(caught.exception))
        self.assertTrue(all(stream.closed for stream in (process.stdin, process.stdout, process.stderr)))

    def test_zombie_only_owned_inventory_reaps_root_without_signalling_group(self):
        process = Mock(pid=41, returncode=0)
        inventory = SimpleNamespace(returncode=0, stdout='41 41 Z\n42 70 Zs\n43 80 X\n')
        with patch.object(bridge_process.Path, 'is_file', return_value=True), \
                patch.object(bridge_process.subprocess, 'run', return_value=inventory), \
                patch.object(bridge_process.os, 'getsid', return_value=41, create=True), \
                patch.object(bridge_process, 'signal_session') as signal_owned, \
                patch.object(bridge_process, 'stop_process') as fallback:
            bridge_process.stop_session(process)
        signal_owned.assert_not_called()
        fallback.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    def test_exited_leader_does_not_hide_live_owned_descendant_group(self):
        process = Mock(pid=41, returncode=0)
        with patch.object(bridge_process, 'session_groups', side_effect=[{70: [12]}, {}]), \
                patch.object(bridge_process.os, 'getsid', return_value=41, create=True), \
                patch.object(bridge_process.os, 'getpgid', return_value=70, create=True), \
                patch.object(bridge_process.os, 'killpg', create=True) as kill, \
                patch.object(bridge_process.time, 'sleep'), \
                patch.object(bridge_process, 'stop_process') as fallback:
            bridge_process.stop_session(process)
        kill.assert_called_once_with(70, signal.SIGTERM)
        fallback.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    def test_permission_denied_for_live_owned_member_remains_unverified_failure(self):
        process = Mock(pid=41, returncode=0)
        with patch.object(bridge_process, 'session_groups', return_value={70: [12]}), \
                patch.object(bridge_process.os, 'getsid', return_value=41, create=True), \
                patch.object(bridge_process.os, 'getpgid', return_value=70, create=True), \
                patch.object(bridge_process.os, 'killpg', side_effect=PermissionError('denied'), create=True), \
                patch.object(bridge_process, 'stop_process') as fallback:
            with self.assertRaises(PermissionError) as caught:
                bridge_process.stop_session(process)
        receipt = caught.exception._owned_bridge_receipt
        self.assertEqual(receipt['stage'], 'session_sigterm')
        self.assertEqual(receipt['last_verified_owned_processes'], [dict(pid=12, pgid=70)])
        self.assertFalse(receipt['session_verified_empty'])
        self.assertFalse(receipt['retry_safe'])
        fallback.assert_called_once_with(process, grace=15)

    def test_signals_revalidate_sid_and_pgid_before_touching_a_group(self):
        with patch.object(bridge_process.os, 'getsid', side_effect=[41, 99], create=True), \
                patch.object(bridge_process.os, 'getpgid', return_value=70, create=True), \
                patch.object(bridge_process.os, 'killpg', create=True) as kill:
            bridge_process.signal_session(41, {70: [12], 80: [13]}, signal.SIGTERM)
        kill.assert_called_once_with(70, signal.SIGTERM)

    def test_signal_ownership_mock_contract_needs_no_host_posix_attributes(self):
        result = unittest.TestResult()
        # Windows has none of these POSIX APIs. Run the same ownership contract
        # with an empty host namespace, rather than skipping its assertions.
        with patch.object(bridge_process, 'os', SimpleNamespace()):
            type(self)('test_signals_revalidate_sid_and_pgid_before_touching_a_group').run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(result.skipped, [])

    def windows(self, *, cancelled=False, timeout=5, cleanup_error=False):
        events = []
        class Job:
            def __init__(self, argv, **_):
                events.append('owned-before-start')
                self.args = argv; self.returncode = None if cancelled or timeout == 0 else 0
                self.stdout = io.BytesIO(b'')
                envelope = json.loads(Path(argv[-1]).read_text())
                self.directory = Path(argv[-1]).parent
                self.assert_payload = Path(envelope['stdin']).read_text()
                Path(envelope['stdout']).write_text('{"schema":1,"result":"fixture"}')
                Path(envelope['stderr']).write_text('separate diagnostic')
            def poll(self): return self.returncode
            def kill_tree(self): events.append('kill-job'); self.returncode = -1
            def wait(self, timeout=None): events.append('reap-root'); return self.returncode
            def wait_tree(self, timeout=None):
                events.append('job-empty')
                if cleanup_error: raise subprocess.TimeoutExpired(self.args, timeout)
            def close(self): events.append('close-handles')
        module = ModuleType('build_manager.windows_process'); module.WindowsProcess = Job
        def stop(process, *, grace):
            self.assertEqual(grace, 15); process.kill_tree(); process.wait(timeout=grace)
        with patch.dict(sys.modules, {'build_manager.windows_process': module}), \
                patch.object(bridge_process, 'stop_process', side_effect=stop):
            if cancelled or timeout == 0 or cleanup_error:
                with self.assertRaisesRegex(ValueError, 'teardown' if cleanup_error else 'cancelled' if cancelled else 'timed out'):
                    bridge_process.run_windows(['python', 'bridge.py'], '{}', cwd='.', env={}, timeout=timeout,
                                               cancelled=lambda: cancelled)
                result = None
            else:
                result = bridge_process.run_windows(['python', 'bridge.py'], '{}', cwd='.', env={}, timeout=timeout,
                                                    cancelled=lambda: False)
        self.assertEqual(events, ['owned-before-start', 'kill-job', 'reap-root', 'job-empty', 'close-handles'])
        return result

    def test_windows_protocol_is_separate_and_job_is_retired_after_root_exit(self):
        result = self.windows()
        self.assertEqual(json.loads(result.stdout)['result'], 'fixture')
        self.assertEqual(result.stderr, 'separate diagnostic')

    def test_windows_cancel_and_timeout_wait_for_owned_job(self):
        self.windows(cancelled=True); self.windows(timeout=0)

    def test_windows_job_drain_failure_is_not_reported_as_clean_cancel(self):
        self.windows(cancelled=True, cleanup_error=True)
