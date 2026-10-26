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

from build_manager.parallels import Parallels

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

    def test_selected_guest_is_explicit_and_suspended_vm_is_not_resumed(self):
        client = Parallels('/fixture/prlctl')
        row = dict(uuid=VM, name='Synthetic Linux', status='suspended')
        with patch.object(client, 'inventory', return_value=[row]), patch('subprocess.run') as execute:
            with self.assertRaises(ValueError):
                client.start('')
            with self.assertRaises(ValueError):
                client.start('Synthetic Linux')
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
