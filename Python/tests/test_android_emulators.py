"""Missing tools and mismatched identities never authorize emulator actions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.android_emulators import AndroidEmulator


class AndroidLeaseTests(unittest.TestCase):
    def test_console_shutdown_waits_for_transient_defunct_process_without_signalling(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);client=AndroidEmulator(root/'sdk',root/'owned');client.workspace.mkdir()
            (client.workspace/'avds').mkdir();(client.workspace/'user').mkdir()
            record=dict(token='fixture',name='build-manager-fixture',serial='emulator-5580',
                        workspace=str(client.workspace.resolve()),pid=123,process_started='owned launcher')
            client.marker.write_text(json.dumps(record))
            with patch.object(client,'invoke',side_effect=['build-manager-fixture\nOK','OK']), \
                 patch('build_manager.process_identity.read_process_fingerprint',side_effect=['defunct command',None,None]), \
                 patch('build_manager.process_identity.stop_owned_process') as stop:
                client.cleanup()
                stop.assert_not_called()
            self.assertFalse(client.marker.exists());self.assertFalse((client.workspace/'avds').exists())
            self.assertTrue((client.workspace/'removed-lease.json').exists())

    def test_start_holds_host_lock_until_console_registration(self):
        from contextlib import contextmanager
        with TemporaryDirectory() as folder:
            client = AndroidEmulator(Path(folder)/'sdk', Path(folder)/'owned')
            held = []
            @contextmanager
            def locked(path, **kwargs):
                self.assertEqual(path, Path(folder)/'manager/locks/android-emulator-ports.lock')
                held.append(True)
                try:
                    yield
                finally:
                    held.pop()
            def launch(*args):
                self.assertEqual(held, [True])
                return {'ready': True}
            def ready(record):
                self.assertEqual(held, [])
                return record
            with patch.object(client, 'inspect'), patch('build_manager.locking.workspace_lock', locked), \
                 patch('build_manager.registry.config_directory', return_value=Path(folder)/'manager'), \
                 patch.object(client, '_launch', side_effect=launch), \
                 patch.object(client, '_wait_ready', side_effect=ready):
                self.assertEqual(client.start('image', 'model'), {'ready': True})
            self.assertEqual(held, [])

    def test_conflicting_serial_cleans_only_creation_checked_process(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);client=AndroidEmulator(root/'sdk',root/'owned');client.workspace.mkdir()
            (client.workspace/'avds').mkdir()
            original='Tue Nov  3 22:17:58 2026 emulator -avd build-manager-fixture'
            current='Tue Nov  3 22:17:58 2026 qemu -avd build-manager-fixture'
            record=dict(token='fixture',name='build-manager-fixture',serial='emulator-5580',
                        workspace=str(client.workspace.resolve()),pid=123,process_started=original)
            client.marker.write_text(json.dumps(record))
            with patch.object(client,'invoke',return_value='another-avd\nOK') as invoke, \
                 patch('build_manager.process_identity.read_process_fingerprint',side_effect=[current,None,None]), \
                 patch('build_manager.process_identity.stop_owned_process') as stop:
                client.cleanup()
                self.assertEqual(invoke.call_count,1)
                stop.assert_called_once_with(123,current,token='build-manager-fixture')
            self.assertFalse(client.marker.exists())
            self.assertTrue((client.workspace/'removed-lease.json').exists())

    def test_startup_timeout_is_bounded_and_defaults_to_four_minutes(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(AndroidEmulator(root/'sdk',root/'owned').startup_timeout,240)
            self.assertEqual(AndroidEmulator(root/'sdk',root/'owned',startup_timeout=600).startup_timeout,600)
            for value in (0,-1,3601,True,1.5):
                with self.assertRaises(ValueError):
                    AndroidEmulator(root/'sdk',root/'owned',startup_timeout=value)

    def test_supported_ports_exhausted_never_launches_on_an_undiscoverable_port(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            client = AndroidEmulator(root/'sdk', root/'owned')
            # Include offline transports: their ports are still occupied.
            devices = 'List of devices attached\n' + '\n'.join(
                f'emulator-{port}\t' + ('device' if port % 4 else 'offline')
                for port in range(5554, 5586, 2))
            with patch.object(client, 'inspect'), patch.object(client, 'invoke', return_value=devices), \
                 patch('build_manager.registry.config_directory', return_value=root/'manager'), \
                 patch('build_manager.android_emulators.socket.socket',
                       side_effect=AssertionError('No supported port remains')), \
                 patch('build_manager.android_emulators.subprocess.run') as create:
                with self.assertRaisesRegex(RuntimeError, 'No unused emulator'):
                    client.start('system-images;android-36;google_apis;arm64-v8a', 'pixel_9')
            create.assert_not_called()
            self.assertFalse(client.marker.exists())

    def test_graphics_selection_is_explicit_and_recordable(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(AndroidEmulator(root/'sdk',root/'owned').gpu,'auto')
            self.assertEqual(AndroidEmulator(root/'sdk',root/'owned',gpu='swiftshader').gpu,'swiftshader')
            with self.assertRaises(ValueError):
                AndroidEmulator(root/'sdk',root/'owned',gpu='unknown')

    def test_low_disk_startup_cause_survives_disposable_log_removal(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            client = AndroidEmulator(root / 'sdk', root / 'owned')
            client.workspace.mkdir()
            log = client.workspace / 'emulator.log'
            log.write_text('FATAL | Not enough space to create userdata partition. '
                           'Available: 3088.63 MB at /private/synthetic/path, need 7372.80 MB.\n')
            message = client.startup_failure()
            self.assertIn('3088.63 MB', message)
            self.assertIn('7372.80 MB', message)
            self.assertIn('build-manager storage', message)
            self.assertNotIn('/private/synthetic/path', message)
            log.unlink()
            self.assertIn('inspect emulator.log', client.startup_failure())

    def test_incomplete_sdk_fails_without_starting_or_creating_avd(self):
        with TemporaryDirectory() as folder, patch('build_manager.hosts.android_host_issue', return_value=None), patch('build_manager.android_emulators.subprocess.check_output') as run:
            root=Path(folder);client=AndroidEmulator(root/'missing-sdk',root/'owned')
            with self.assertRaisesRegex(ValueError,'complete system image'):
                client.start('system-images;android-36;google_apis;arm64-v8a','pixel_9')
            run.assert_not_called()
            self.assertFalse(client.workspace.exists())

    def test_mismatched_avd_name_never_kills_or_removes_owned_workspace(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);client=AndroidEmulator(root/'sdk',root/'owned');client.workspace.mkdir()
            record=dict(token='fixture',name='build-manager-fixture',serial='emulator-5580',workspace=str(client.workspace.resolve()))
            client.marker.write_text(json.dumps(record))
            with patch.object(client,'invoke',return_value='unrelated-user-emulator\\nOK') as run:
                with self.assertRaisesRegex(ValueError,'another emulator'):
                    client.cleanup()
                self.assertEqual(run.call_count,1)
                self.assertNotIn('kill',run.call_args.args)
                self.assertTrue(client.marker.exists())

    def test_unsupported_host_fails_before_tool_execution_or_workspace_creation(self):
        with TemporaryDirectory() as folder, patch('build_manager.android_emulators.subprocess.check_output') as run:
            root = Path(folder)
            client = AndroidEmulator(root/'sdk', root/'owned')
            for system in ('Windows', 'Linux'):
                for architecture, abi, message in (('ARM64', 'arm64-v8a', 'host binary'),
                                                    ('AMD64', 'x86_64', 'Known limitation')):
                    with self.subTest(system=system, architecture=architecture), patch('build_manager.hosts.platform.system', return_value=system), patch('build_manager.hosts.platform.machine', return_value=architecture):
                        with self.assertRaisesRegex(ValueError, message):
                            client.start('system-images;android-36;google_apis;'+abi, 'pixel_9')
            run.assert_not_called()
            self.assertFalse(client.workspace.exists())
