"""Cleanup is limited to the exact device and ownership label created by a run."""
import json
from types import SimpleNamespace
import unittest

from build_manager.apple_simulators import AppleSimulators

DEVICE = '00000000-0000-0000-0000-000000000001'


class SimulatorLeaseTests(unittest.TestCase):
    def test_different_ownership_label_never_shuts_down_or_deletes_device(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'devices': {'fixture-runtime': [dict(udid=DEVICE, name='User simulator', state='Booted')]}}))
        client = AppleSimulators(runner=runner)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            client.remove(DEVICE, 'Owned fixture')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2:4], ['list', 'devices'])

    def test_owned_device_cleanup_is_bounded_and_missing_device_is_idempotent(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            rows = [dict(udid=DEVICE, name='Owned fixture', state='Booted')]
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'devices': {'fixture-runtime': rows}}))
        AppleSimulators(runner=runner).remove(DEVICE, 'Owned fixture')
        self.assertEqual([command[2] for command in calls], ['list', 'shutdown', 'delete'])
        self.assertTrue(all('all' not in command for command in calls))

    def test_shutdown_race_requires_verified_same_lease_before_delete(self):
        from unittest.mock import patch
        client=AppleSimulators()
        with patch.object(client,'matching',side_effect=[dict(state='Booted'),dict(state='Shutdown')]), patch.object(client,'invoke',side_effect=[RuntimeError('already shutdown'), '']) as invoke:
            client.remove(DEVICE,'Owned fixture')
            self.assertEqual([c.args[0] for c in invoke.call_args_list],['shutdown','delete'])
        with patch.object(client,'matching',side_effect=[dict(state='Booted'),dict(state='Booted')]), patch.object(client,'invoke',side_effect=RuntimeError('real shutdown failure')) as invoke:
            with self.assertRaisesRegex(RuntimeError,'real shutdown failure'):
                client.remove(DEVICE,'Owned fixture')
            self.assertEqual(invoke.call_count,1)
