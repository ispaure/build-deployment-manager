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
                 patch('build_manager.process_identity.identity',side_effect=['defunct command',None,None]), \
                 patch('build_manager.process_identity.stop_owned') as stop:
                client.cleanup()
                stop.assert_not_called()
            self.assertFalse(client.marker.exists());self.assertFalse((client.workspace/'avds').exists())
            self.assertTrue((client.workspace/'removed-lease.json').exists())

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
