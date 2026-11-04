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
        try:
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                self.invoke(argv, cancelled=lambda: (self.root / 'grandchild.ready').exists())
            self.assertLess(time.monotonic() - started, bridge_process.STOP_GRACE + 8)
            self.assertIsNone(sentinel.poll())
            self.assert_retired()
        finally:
            bridge_process.stop_process(sentinel, grace=.1)

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


class BridgeOwnershipUnitTests(unittest.TestCase):
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

    def test_signals_revalidate_sid_and_pgid_before_touching_a_group(self):
        with patch.object(bridge_process.os, 'getsid', side_effect=[41, 99]), \
                patch.object(bridge_process.os, 'getpgid', return_value=70), \
                patch.object(bridge_process.os, 'killpg') as kill:
            bridge_process.signal_session(41, {70: [12], 80: [13]}, signal.SIGTERM)
        kill.assert_called_once_with(70, signal.SIGTERM)

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
