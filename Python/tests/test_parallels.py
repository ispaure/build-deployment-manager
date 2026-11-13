"""Transport contracts use literal arguments and only explicitly selected guests."""
import base64
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.parallels import Parallels, ParallelsStartTimeout

VM = '00000000-0000-0000-0000-000000000001'


class ParallelsTransportTests(unittest.TestCase):
    def test_saved_uuid_matches_braced_inventory_and_ambiguous_names_fail(self):
        client = Parallels('/fixture/prlctl')
        row = dict(uuid='{' + VM + '}', name='Dedicated test', status='stopped')
        with patch.object(client, 'inventory', return_value=[row]):
            self.assertEqual(client.selected(VM), row)
        with patch.object(client, 'inventory', return_value=[row, dict(row, uuid='other')]):
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                client.selected('Dedicated test')

    def test_windows_parameters_are_encoded_data_and_use_existing_interactive_user(self):
        client = Parallels('/fixture/prlctl')
        value = "a'; Stop-Process -Id 123; 'Unicode—value"
        command = client.powershell_command(VM)
        script = base64.b64decode(command[-1]).decode('utf-16le')
        self.assertNotIn(value, script)
        self.assertIn('--current-user', command)
        self.assertNotIn('-ExecutionPolicy', command)
        import json
        envelope = json.loads(client.powershell_payload('$p.value | ConvertTo-Json', {'value': value}, b'fixture'))
        self.assertEqual(envelope['values'], {'value': value})
        self.assertEqual(base64.b64decode(envelope['data']), b'fixture')
        self.assertLess(len(' '.join(command)), 2000)

    def test_guest_shell_round_trip_preserves_metacharacters_as_literal_arguments(self):
        client = Parallels('/fixture/prlctl')
        arguments = ['python3', '-c', 'import sys; print(sys.argv[1])', "a b; $(touch /tmp/never) 'quoted'"]
        command = client.command(VM, arguments)
        self.assertEqual(shlex.split(' '.join(command[3:])), arguments)
        with self.assertRaises(ValueError):
            client.command('--help', ['true'])

    def test_fixed_workspace_inspection_checks_only_the_exact_namespace_without_login(self):
        client = Parallels('/fixture/prlctl')
        token = 'a' * 32
        receipt = dict(token=token, workspace='C:\\Public\\bm\\' + token,
                       exists=False, owner_verified=False)
        with patch('build_manager.parallels.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 0, json.dumps(receipt).encode(), b'')) as execute:
            self.assertEqual(client.inspect_windows_workspace(VM, token), receipt)
            self.assertNotIn('--current-user', execute.call_args.args[0])
            envelope = json.loads(execute.call_args.kwargs['input'])
            self.assertEqual(envelope['values'], dict(token=token))
            self.assertIn('ReparsePoint', envelope['script'])
            self.assertIn('Workspace ownership mismatch', envelope['script'])
            for forbidden in ('Remove-Item', 'Set-Content', 'Start-Process', 'New-Item'):
                self.assertNotIn(forbidden, envelope['script'])
        with patch('build_manager.parallels.subprocess.run') as execute:
            with self.assertRaises(ValueError):
                client.inspect_windows_workspace(VM, '../foreign')
            execute.assert_not_called()
        receipt['token'] = 'b' * 32
        with patch('build_manager.parallels.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 0, json.dumps(receipt).encode(), b'')):
            with self.assertRaisesRegex(ValueError, 'inspection receipt'):
                client.inspect_windows_workspace(VM, token)

    def test_empty_current_user_failure_diagnoses_signin_without_replaying_script(self):
        client = Parallels('/fixture/prlctl')
        failure = subprocess.CompletedProcess([], 1, b'', b'')
        absent = subprocess.CompletedProcess([], 1, b'', b'No User exists for *\r\n')
        with patch('build_manager.parallels.subprocess.run', side_effect=[failure, absent]) as execute:
            with self.assertRaisesRegex(RuntimeError, 'No interactive Windows user'):
                client.powershell(VM, 'potentially-mutating-script', timeout=30)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(execute.call_args.args[0], ['/fixture/prlctl', 'exec', VM, 'query.exe', 'user'])
            self.assertEqual(execute.call_args.kwargs['timeout'], 10)
        for diagnosis in (subprocess.CompletedProcess([], 0, b'active user', b''),
                          subprocess.TimeoutExpired('query', 10)):
            with self.subTest(diagnosis=diagnosis), patch(
                    'build_manager.parallels.subprocess.run', side_effect=[failure, diagnosis]):
                with self.assertRaisesRegex(RuntimeError, r'failed \(1\): $'):
                    client.powershell(VM, 'potentially-mutating-script')

    def test_selected_guest_is_explicit_and_suspended_vm_is_not_resumed(self):
        client = Parallels('/fixture/prlctl')
        row = dict(uuid=VM, name='Synthetic Linux', status='suspended')
        with patch.object(client, 'inventory', return_value=[row]), patch('subprocess.run') as execute:
            with self.assertRaises(ValueError):
                client.start('')
            with self.assertRaises(ValueError):
                client.start('Synthetic Linux')
            execute.assert_not_called()

    def test_stopped_start_timeout_retains_exact_request_and_original_state(self):
        client = Parallels('/fixture/prlctl')
        row = dict(uuid='{' + VM + '}', name='Dedicated test', status='stopped')
        argv = ['/fixture/prlctl', 'start', row['uuid']]
        original = subprocess.TimeoutExpired(argv, 120, b'partial stdout', b'partial stderr')
        with (patch.object(client, 'inventory', return_value=[row]) as inventory,
              patch('build_manager.parallels.subprocess.run', side_effect=original) as execute):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                client.start('Dedicated test')
        error = raised.exception
        self.assertIsInstance(error, ParallelsStartTimeout)
        self.assertEqual((error.uuid, error.original_state), (row['uuid'], 'stopped'))
        self.assertEqual((error.cmd, error.timeout, error.output, error.stderr),
                         (original.cmd, original.timeout, original.output, original.stderr))
        self.assertEqual(str(error), str(original))
        self.assertIs(error.__cause__, original)
        inventory.assert_called_once_with()
        execute.assert_called_once_with(argv, check=True, timeout=120)

    def test_inventory_timeout_before_start_stays_an_ordinary_timeout(self):
        client = Parallels('/fixture/prlctl')
        error = subprocess.TimeoutExpired(['/fixture/prlctl', 'list', '--all', '--json'], 30)
        with (patch.object(client, 'inventory', side_effect=error),
              patch('build_manager.parallels.subprocess.run') as execute):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                client.start(VM)
        self.assertIs(raised.exception, error)
        execute.assert_not_called()

    def test_stage_allowlist_excludes_private_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'public.py').write_text('pass')
            (root / 'credential').write_text('synthetic-secret')
            client = Parallels('/fixture/prlctl')
            with patch.object(client, 'execute') as execute:
                client.stage(VM, root, '/var/tmp/example', 'example', 1000, 1000, members=['public.py'])
            import json, hashlib
            envelope = json.loads(execute.call_args.kwargs['data'])
            data = base64.b64decode(envelope['archive'])
            runner = base64.b64decode(envelope['runner'])
            self.assertEqual(runner, Path(__import__('build_manager.parallels', fromlist=['x']).__file__).with_name('guest.py').read_bytes())
            self.assertEqual(hashlib.sha256(runner).hexdigest(), execute.call_args.args[1][-1])
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
                self.assertEqual(archive.getnames(), ['public.py'])
                self.assertNotIn(b'synthetic-secret', archive.extractfile('public.py').read())

    def test_timed_out_stage_recovers_matching_receipt_without_second_upload(self):
        from build_manager.parallels import STAGE, INSPECT_STAGE
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'public.py').write_text('pass')
            client = Parallels('/fixture/prlctl')
            def execute(vm, argv, **kwargs):
                if argv[2] == STAGE:
                    raise subprocess.TimeoutExpired('upload', 180)
                self.assertEqual(argv[2], INSPECT_STAGE)
                workspace, token, digest, uid, gid, runner = argv[3:]
                return json.dumps(dict(state='complete', identity=dict(token=token,
                    archive_sha256=digest, uid=int(uid), gid=int(gid), runner_sha256=runner))).encode()
            with patch.object(client, 'execute', side_effect=execute) as calls:
                client.stage(VM, root, '/var/tmp/token', 'token', 1000, 1000, members=['public.py'])
            self.assertEqual(calls.call_count, 2)

    def test_stage_unknown_observations_cannot_extend_total_deadline(self):
        from build_manager.parallels import STAGE
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'public.py').write_text('pass')
            client = Parallels('/fixture/prlctl')
            clock = [0.]
            def execute(vm, argv, **kwargs):
                clock[0] += kwargs['timeout']
                raise subprocess.TimeoutExpired('transport', kwargs['timeout'])
            with patch.object(client, 'execute', side_effect=execute) as calls, \
                    patch('build_manager.parallels.time.monotonic', side_effect=lambda: clock[0]), \
                    patch('build_manager.parallels.time.sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0]+delay)):
                with self.assertRaisesRegex(RuntimeError, 'unknown'):
                    client.stage(VM, root, '/var/tmp/token', 'token', 1000, 1000, members=['public.py'])
            self.assertEqual(clock[0], 210.)
            self.assertEqual(sum(c.args[1][2] == STAGE for c in calls.call_args_list), 1)

    def test_large_linux_command_is_stdin_data_not_guest_command_line(self):
        import json
        from threading import Event
        from unittest.mock import MagicMock
        client=Parallels('/fixture/prlctl')
        process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.stdin=io.BytesIO()
        saved=[]
        process.stdin.close=lambda:saved.append(process.stdin.getvalue())
        arguments=['python3','-c','print('+repr('large literal '*2000)+')']
        with patch('build_manager.parallels.subprocess.Popen',return_value=process) as spawn:
            self.assertEqual(client.run_owned(VM,'/var/tmp/owned','owned',1000,arguments,{},Event(),timeout=10),0)
        self.assertLess(len(' '.join(spawn.call_args.args[0])),1000)
        self.assertIn('/var/tmp/owned/.manager-guest.py', shlex.split(' '.join(spawn.call_args.args[0][3:])))
        self.assertEqual(json.loads(base64.b64decode(saved[0]))['argv'],arguments)

    def test_only_idempotent_cleanup_retries_known_tools_failure(self):
        client=Parallels('/fixture/prlctl')
        with patch.object(client,'execute',side_effect=[RuntimeError('Guest command failed (255): Invalid argument'),b'cleaned']) as execute, patch('build_manager.parallels.time.sleep'):
            self.assertEqual(client.cleanup(VM,['owned-cleanup']),b'cleaned')
            self.assertEqual(execute.call_count,2)
        with patch.object(client,'execute',side_effect=RuntimeError('ownership mismatch')) as execute:
            with self.assertRaisesRegex(RuntimeError,'ownership'):
                client.cleanup(VM,['owned-cleanup'])
            self.assertEqual(execute.call_count,1)

    def test_idempotent_setup_retries_session_admission_but_never_other_errors(self):
        client = Parallels('/fixture/prlctl')
        transient = RuntimeError('Guest command failed (255): Unable to open new session')
        with patch.object(client, 'execute', side_effect=[transient, b'written']) as execute, patch('build_manager.parallels.time.sleep'):
            self.assertEqual(client.execute_idempotent(VM, ['owned-plan-write'], data=b'plan'), b'written')
            self.assertEqual(execute.call_args_list[0], execute.call_args_list[1])
        with patch.object(client, 'execute', side_effect=transient) as execute, patch('build_manager.parallels.time.sleep'):
            with self.assertRaises(RuntimeError): client.execute_idempotent(VM, ['owned-plan-write'])
            self.assertEqual(execute.call_count, 3)
        with patch.object(client, 'execute', side_effect=RuntimeError('Guest command failed (1): ownership mismatch')) as execute:
            with self.assertRaisesRegex(RuntimeError, 'ownership'): client.execute_idempotent(VM, ['owned-plan-write'])
            self.assertEqual(execute.call_count, 1)

    def test_owned_file_payload_never_consumes_guest_command_line(self):
        client = Parallels('/fixture/prlctl')
        payload = ('large plan 😀 ' * 3000).encode()
        with patch.object(client, 'execute_idempotent') as execute:
            client.write_owned(VM, '/var/tmp/owned', 'owned', 'plan.json', payload, 1000, 1000)
        self.assertLess(len(' '.join(execute.call_args.args[1])), 2000)
        self.assertEqual(base64.b64decode(execute.call_args.kwargs['data']), payload)
        with self.assertRaises(ValueError):
            client.write_owned(VM, '/var/tmp/owned', 'owned', '../escape', payload, 1000, 1000)

    @unittest.skipUnless(os.name == 'posix', 'Linux transport file ownership contract')
    def test_owned_write_does_not_follow_a_destination_symlink(self):
        from build_manager.parallels import WRITE
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(); owned = root/'owned'; owned.mkdir()
            (owned/'.manager-owned.json').write_text(json.dumps(dict(token='owned')))
            target = root/'target'; target.write_bytes(b'retained')
            (owned/'plan.json').symlink_to(target)
            result = subprocess.run([sys.executable, '-c', WRITE, str(owned), 'owned',
                'plan.json', str(os.getuid()), str(os.getgid())], input=base64.b64encode(b'new'), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b'retained')

    def test_lost_linux_result_retries_the_same_receipt_aware_invocation(self):
        from threading import Event
        from unittest.mock import MagicMock
        client = Parallels('/fixture/prlctl')
        processes = []
        payloads = []
        for code in (255, 0):
            process = MagicMock(); process.poll.return_value = code; process.returncode = code
            process.stdin = io.BytesIO()
            process.stdin.close = lambda stream=process.stdin: payloads.append(stream.getvalue())
            processes.append(process)
        with patch('build_manager.parallels.subprocess.Popen', side_effect=processes) as spawn, patch('build_manager.parallels.time.sleep'):
            self.assertEqual(client.run_owned(VM, '/var/tmp/owned', 'owned', 1000,
                ['real-test'], {}, Event(), timeout=10), 0)
        self.assertEqual(spawn.call_args_list[0], spawn.call_args_list[1])
        self.assertEqual(payloads[0], payloads[1])
        self.assertIn('--invocation', shlex.split(' '.join(spawn.call_args.args[0][3:])))

    def test_linux_command_failure_is_not_a_transport_retry(self):
        from threading import Event
        from unittest.mock import MagicMock
        process = MagicMock(); process.poll.return_value = 2; process.returncode = 2
        with patch('build_manager.parallels.subprocess.Popen', return_value=process) as spawn:
            self.assertEqual(Parallels('/fixture/prlctl').run_owned(VM, '/var/tmp/owned',
                'owned', 1000, ['failed-test'], {}, Event(), timeout=10), 2)
        self.assertEqual(spawn.call_count, 1)


@unittest.skipUnless(os.name == 'posix', 'POSIX process group cancellation')
class LinuxTransportCancellationTests(unittest.TestCase):
    def test_adapter_signal_cancels_guest_before_transport_exits(self):
        import signal
        import time
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready, proof = root / 'ready', root / 'cancelled'
            transport = "import os,pathlib,sys,time; sys.stdin.buffer.read(); pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(15)"
            script = f"""import os,signal,sys
from pathlib import Path
from threading import Event
from build_manager.parallels import Parallels
cancelled=Event()
signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
class LocalTransport(Parallels):
 def command(self, *args):
  return [sys.executable, '-c', {transport!r}, {str(ready)!r}]
 def cancel(self, *args):
  pid=int(Path({str(ready)!r}).read_text())
  os.kill(pid, 0)
  Path({str(proof)!r}).write_text('guest-cancelled-before-transport-exit')
  os.kill(pid, signal.SIGTERM)
code=LocalTransport('/fixture/prlctl').run_owned('vm','workspace','token',1000,['test'],{{}},cancelled,timeout=10)
assert code==130, code
"""
            adapter = subprocess.Popen([sys.executable, '-c', script], start_new_session=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and adapter.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'Owned transport did not start')
                os.killpg(adapter.pid, signal.SIGTERM)
                _, error = adapter.communicate(timeout=5)
                self.assertEqual(adapter.returncode, 0, error)
                self.assertEqual(proof.read_text(), 'guest-cancelled-before-transport-exit')
            finally:
                if adapter.poll() is None:
                    os.killpg(adapter.pid, signal.SIGKILL)
                adapter.communicate(timeout=20)
