"""Missing tools and mismatched identities never authorize emulator actions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.android_emulators import AndroidEmulator


class AndroidLeaseTests(unittest.TestCase):
    def test_incomplete_sdk_fails_without_starting_or_creating_avd(self):
        with TemporaryDirectory() as folder, patch('build_manager.android_emulators.subprocess.check_output') as run:
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
