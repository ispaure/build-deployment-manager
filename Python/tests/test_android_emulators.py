"""Missing tools and mismatched identities never authorize emulator actions."""
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

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


class HostedAndroidAdmissionTests(unittest.TestCase):
    image = 'system-images;android-36;google_apis;x86_64'
    markers = dict(GITHUB_ACTIONS='true', RUNNER_OS='Linux', RUNNER_ARCH='X64')
    host = dict(system='Linux', architecture='x86_64', kernel='fixture', python='fixture')
    acceleration = 'accel:\n0\nKVM (version 12) is installed and usable.\naccel\n'

    def setUp(self):
        self.folder = self.enterContext(TemporaryDirectory())
        self.root = Path(self.folder)
        self.client = AndroidEmulator(self.root/'sdk', self.root/'owned', execution_context='github-actions')
        self.properties = self.client.sdk/'system-images/android-36/google_apis/x86_64/source.properties'
        for path in [self.client.adb, self.client.emulator, self.client.avdmanager,
                     self.properties, self.properties.with_name('system.img')]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.properties.write_text('SystemImage.Abi=x86_64\n')
        self.enterContext(patch.dict(os.environ, self.markers, clear=True))
        self.enterContext(patch('build_manager.hosts.host_identity', return_value=self.host))

    def test_explicit_hosted_admission_requires_actual_host_kvm_and_complete_native_image(self):
        with patch.object(self.client, '_verify_hosted_kvm') as kvm, \
                patch('build_manager.android_emulators.subprocess.check_output', return_value=self.acceleration) as check:
            self.assertEqual(self.client.inspect(self.image), self.acceleration.strip())
        kvm.assert_called_once()
        check.assert_called_once()
        self.assertEqual(check.call_args.args[0], [str(self.client.emulator), '-accel-check'])
        proof = self.client.admission
        self.assertEqual(proof['execution_context'], 'github-actions')
        self.assertEqual(proof['host'], self.host)
        self.assertEqual(proof['acceleration'], 'KVM')
        self.assertTrue(proof['acceleration_verified'])
        self.assertTrue(proof['kvm_device_accessible'])
        self.assertFalse(self.client.workspace.exists())

    def test_markers_or_constructor_environment_alone_do_not_enable_local_linux(self):
        client = AndroidEmulator(self.client.sdk, self.root/'local', environment=self.markers)
        self.assertEqual(client.execution_context, 'local')
        with patch('build_manager.hosts.platform.system', return_value='Linux'), \
                patch('build_manager.hosts.platform.machine', return_value='x86_64'), \
                patch('build_manager.android_emulators.subprocess.check_output') as check:
            with self.assertRaisesRegex(ValueError, 'Known limitation'):
                client.start(self.image, 'pixel_9')
        check.assert_not_called()
        self.assertFalse(client.workspace.exists())

    def test_hosted_context_rejects_wrong_host_and_missing_real_runner_markers(self):
        with patch('build_manager.android_emulators.subprocess.check_output') as check, \
                patch.object(self.client, '_verify_hosted_kvm') as kvm:
            for system, architecture in [('Darwin', 'x86_64'), ('Windows', 'AMD64'), ('Linux', 'aarch64')]:
                with self.subTest(system=system, architecture=architecture), \
                        patch('build_manager.hosts.host_identity', return_value=dict(system=system, architecture=architecture)):
                    with self.assertRaisesRegex(ValueError, 'actual Linux x64'):
                        self.client.start(self.image, 'pixel_9')
            for key, value in [('GITHUB_ACTIONS', 'false'), ('RUNNER_OS', 'Windows'), ('RUNNER_ARCH', 'ARM64')]:
                with self.subTest(marker=key), patch.dict(os.environ, {key: value}):
                    client = AndroidEmulator(self.client.sdk, self.root/'other',
                        environment=self.markers, execution_context='github-actions')
                    with self.assertRaisesRegex(ValueError, 'runner markers'):
                        client.start(self.image, 'pixel_9')
            check.assert_not_called()
            kvm.assert_not_called()
        self.assertFalse(self.client.workspace.exists())

    def test_missing_or_inaccessible_kvm_fails_before_tools_or_avd(self):
        with patch('build_manager.android_emulators.subprocess.check_output') as check:
            with patch.object(Path, 'is_char_device', return_value=False):
                with self.assertRaisesRegex(ValueError, 'accessible /dev/kvm'):
                    self.client.start(self.image, 'pixel_9')
            with patch.object(Path, 'is_char_device', return_value=True), patch('os.access', return_value=False):
                with self.assertRaisesRegex(ValueError, 'accessible /dev/kvm'):
                    self.client.start(self.image, 'pixel_9')
            with patch.object(Path, 'is_char_device', return_value=True), patch('os.access', return_value=True), \
                    patch('os.open', side_effect=PermissionError):
                with self.assertRaisesRegex(ValueError, 'cannot open /dev/kvm'):
                    self.client.start(self.image, 'pixel_9')
            check.assert_not_called()
        self.assertFalse(self.client.workspace.exists())

    def test_kvm_open_is_read_write_and_descriptor_is_closed(self):
        with patch.object(Path, 'is_char_device', return_value=True), patch('os.access', return_value=True), \
                patch('os.open', return_value=123) as opened, patch('os.close') as closed:
            self.client._verify_hosted_kvm()
        self.assertEqual(opened.call_args.args[0], Path('/dev/kvm'))
        self.assertTrue(opened.call_args.args[1] & os.O_RDWR)
        closed.assert_called_once_with(123)

    def test_incomplete_image_wrong_abi_and_unusable_acceleration_are_never_admitted(self):
        with patch.object(self.client, '_verify_hosted_kvm'), \
                patch('build_manager.android_emulators.subprocess.check_output', return_value=self.acceleration) as check:
            self.properties.with_name('system.img').unlink()
            with self.assertRaisesRegex(ValueError, 'complete system image'):
                self.client.start(self.image, 'pixel_9')
            check.assert_not_called()
            self.properties.with_name('system.img').touch()
            self.properties.write_text('SystemImage.Abi=arm64-v8a\n')
            with self.assertRaisesRegex(ValueError, 'native x86_64 ABI'):
                self.client.start(self.image, 'pixel_9')
            self.properties.write_text('SystemImage.Abi=x86_64\n')
            check.assert_not_called()
            arm_image = self.image.replace('x86_64', 'arm64-v8a')
            arm = self.properties.parent.with_name('arm64-v8a')
            arm.mkdir()
            (arm/'system.img').touch()
            (arm/'source.properties').write_text('SystemImage.Abi=arm64-v8a\n')
            with self.assertRaisesRegex(ValueError, 'not native'):
                self.client.start(arm_image, 'pixel_9')
            check.assert_not_called()
            for output in ['KVM is not installed and usable.', 'accel:\n1\nKVM unavailable.', 'Hypervisor.Framework is installed and usable.']:
                with self.subTest(output=output):
                    check.return_value = output
                    with self.assertRaisesRegex(ValueError, 'usable KVM'):
                        self.client.start(self.image, 'pixel_9')
                    self.assertIsNone(self.client.admission)
            check.return_value = self.acceleration
            with self.assertRaisesRegex(ValueError, 'requires KVM'):
                self.client.inspect(self.image, acceleration='Hypervisor.Framework')
        self.assertFalse(self.client.workspace.exists())

    def test_failed_acceleration_command_cannot_create_an_avd(self):
        with patch.object(self.client, '_verify_hosted_kvm'), \
                patch('build_manager.android_emulators.subprocess.check_output',
                      side_effect=subprocess.CalledProcessError(1, 'emulator -accel-check')), \
                patch('build_manager.android_emulators.subprocess.run') as create:
            with self.assertRaises(subprocess.CalledProcessError):
                self.client.start(self.image, 'pixel_9')
            create.assert_not_called()
        self.assertIsNone(self.client.admission)
        self.assertFalse(self.client.workspace.exists())

    def test_owned_lease_records_verified_hosted_context(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        with patch.object(self.client, '_verify_hosted_kvm'), \
                patch('build_manager.android_emulators.subprocess.check_output', return_value=self.acceleration), \
                patch.object(self.client, 'invoke', return_value='List of devices attached'), \
                patch.object(self.client, 'verify'), patch('build_manager.android_emulators.socket.socket'), \
                patch('build_manager.android_emulators.subprocess.run'), \
                patch('build_manager.android_emulators.subprocess.Popen', return_value=child), \
                patch('build_manager.process_identity.read_process_fingerprint', return_value='owned-process'):
            record = self.client._launch(self.image, 'pixel_9')
        retained = json.loads(self.client.marker.read_text())
        self.assertEqual(retained, record)
        self.assertEqual(retained['execution_context'], 'github-actions')
        self.assertEqual(retained['admission']['host'], self.host)
        self.assertTrue(retained['admission']['acceleration_verified'])
        self.assertEqual(retained['admission']['acceleration'], 'KVM')

    def test_unknown_provider_context_is_not_an_implicit_fallback(self):
        with self.assertRaisesRegex(ValueError, 'execution context'):
            AndroidEmulator(self.client.sdk, self.root/'invalid', execution_context='hosted')
