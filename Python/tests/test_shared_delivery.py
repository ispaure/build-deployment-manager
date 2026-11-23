# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.apple_devices import device_json
from build_manager.retained_evidence import passed_phase_rows, select_artifact, verify_artifact
from commonUtils.runtime.streams import file_sha256


class SharedDeliveryTests(unittest.TestCase):
    def test_device_json_checks_response_and_cleans_up(self):
        cases = [
            ({'info': {'outcome': 'success'}, 'result': {'apps': []}}, None),
            ({'info': {'outcome': 'failure'}, 'result': {}}, 'did not report success'),
            ({'info': {'outcome': 'success'}, 'result': []}, 'invalid result'),
            (None, 'no readable JSON'),
        ]
        arguments = ['device', 'info', 'apps', '--device', 'test-id']
        environment = {'DEVELOPER_DIR': '/test/xcode'}
        for response, error in cases:
            outputs = []

            def run(argv, **options):
                self.assertEqual(argv[:-1], ['xcrun', 'devicectl', *arguments,
                                            '--timeout', '30', '--json-output'])
                self.assertEqual(options['env'], environment)
                self.assertEqual(options['timeout'], 40)
                self.assertTrue(options['check'])
                output = Path(argv[-1])
                outputs.append(output)
                if response is not None:
                    output.write_text(json.dumps(response), encoding='utf-8')

            with self.subTest(response=response), patch('build_manager.apple_devices.subprocess.run',
                                                         side_effect=run) as command:
                if error:
                    with self.assertRaisesRegex(RuntimeError, error):
                        device_json(arguments, env=environment, timeout=30)
                else:
                    self.assertEqual(device_json(arguments, env=environment, timeout=30), {'apps': []})
                command.assert_called_once()
                self.assertFalse(outputs[0].parent.exists())

    def test_device_json_propagates_timeout_without_retry(self):
        with patch('build_manager.apple_devices.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('devicectl', 40)) as command:
            with self.assertRaises(subprocess.TimeoutExpired):
                device_json(['list', 'devices'], timeout=30)
            command.assert_called_once()

    def test_saved_run_selects_exact_receipt_and_can_verify_copy_without_original(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = root / 'prepared' / 'app.zip'
            artifacts = root / 'artifacts'
            artifacts.mkdir()
            captured = artifacts / 'historical-name.zip'
            captured.write_bytes(b'reviewed package')
            receipt = dict(path=str(captured), original_path=str(original), sha256=file_sha256(captured))
            row = dict(id='package', status='passed', artifacts=[receipt])
            report = dict(phases=[row, dict(id='unrelated', status='failed')])
            self.assertEqual(passed_phase_rows(report, ['package']), {'package': row})
            self.assertIs(select_artifact(row, original, copied_under=artifacts), receipt)
            verify_artifact(receipt, file_sha256, verify_original=False)
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                verify_artifact(receipt, file_sha256)
            with self.assertRaisesRegex(ValueError, 'unique artifact'):
                select_artifact(dict(artifacts=[receipt, receipt]), original)
            with self.assertRaisesRegex(ValueError, 'canonical retained copy'):
                select_artifact(row, original, copied_under=root)
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                passed_phase_rows(dict(phases=[row, row]), ['package'])
            with self.assertRaisesRegex(ValueError, 'missing'):
                passed_phase_rows(report, ['missing'])
            captured.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                verify_artifact(receipt, file_sha256, verify_original=False)
