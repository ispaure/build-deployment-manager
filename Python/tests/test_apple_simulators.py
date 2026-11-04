"""Cleanup is limited to the exact device and ownership label created by a run."""
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from build_manager.apple_simulators import AppleSimulators

DEVICE = '00000000-0000-0000-0000-000000000001'
OWNER = 'Owned boot fixture'


class InitialBootTimeoutTests(unittest.TestCase):
    def test_owned_booting_transition_requires_successful_normal_readiness_command(self):
        client = AppleSimulators()
        original = subprocess.TimeoutExpired(['xcrun', 'simctl', 'boot', DEVICE], 60)
        with patch.object(client, 'matching', side_effect=[dict(state='Shutdown'),
                dict(state='Booting'), dict(state='Booted')]) as matching, \
                patch.object(client, 'invoke', side_effect=[original, '']) as invoke, \
                patch('build_manager.apple_simulators.time.monotonic', return_value=0), \
                patch('build_manager.apple_simulators.time.sleep'):
            client.boot(DEVICE, name=OWNER)
        self.assertEqual([call.args for call in invoke.call_args_list],
                         [('boot', DEVICE), ('bootstatus', DEVICE, '-b')])
        self.assertEqual(invoke.call_args_list[-1].kwargs, {'timeout': 180})
        self.assertTrue(all(call.args == (DEVICE, OWNER) for call in matching.call_args_list))
        self.assertTrue(all(0 < call.kwargs['timeout'] <= 5 for call in matching.call_args_list))

    def test_readiness_failure_preserves_original_rpc_timeout_without_reboot(self):
        for failure in (RuntimeError('not ready'), subprocess.TimeoutExpired('bootstatus', 180)):
            with self.subTest(failure=type(failure).__name__):
                client = AppleSimulators()
                original = subprocess.TimeoutExpired('boot', 60)
                with patch.object(client, 'matching', side_effect=[dict(state='Shutdown'), dict(state='Booted')]), \
                        patch.object(client, 'invoke', side_effect=[original, failure]) as invoke, \
                        patch('build_manager.apple_simulators.time.monotonic', return_value=0):
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:
                        client.boot(DEVICE, name=OWNER)
                self.assertIs(caught.exception, original)
                self.assertEqual([call.args[0] for call in invoke.call_args_list], ['boot', 'bootstatus'])

    def test_unknown_state_missing_device_or_lost_ownership_preserves_original_timeout(self):
        for observed in (None, dict(state='Shutdown'), dict(state='Shutting Down'),
                         dict(state='Unknown'), ValueError('ownership changed'),
                         subprocess.TimeoutExpired('list', 5)):
            with self.subTest(observed=observed):
                client = AppleSimulators()
                original = subprocess.TimeoutExpired('boot', 60, output='Booted')
                with patch.object(client, 'matching', side_effect=[dict(state='Shutdown'), observed]), \
                        patch.object(client, 'invoke', side_effect=original) as invoke, \
                        patch('build_manager.apple_simulators.time.monotonic', return_value=0):
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:
                        client.boot(DEVICE, name=OWNER)
                self.assertIs(caught.exception, original)
                invoke.assert_called_once_with('boot', DEVICE)

    def test_booting_observation_has_a_deadline_and_never_reboots(self):
        client = AppleSimulators()
        original = subprocess.TimeoutExpired('boot', 60)
        clock = dict(now=0)
        def elapsed(seconds):
            clock['now'] += 31
        with patch.object(client, 'matching', side_effect=[dict(state='Shutdown'), dict(state='Booting')]), \
                patch.object(client, 'invoke', side_effect=original) as invoke, \
                patch('build_manager.apple_simulators.time.monotonic', side_effect=lambda: clock['now']), \
                patch('build_manager.apple_simulators.time.sleep', side_effect=elapsed) as sleep:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                client.boot(DEVICE, name=OWNER)
        self.assertIs(caught.exception, original)
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)
        invoke.assert_called_once_with('boot', DEVICE)
        sleep.assert_called_once()

    def test_other_booted_device_never_satisfies_owned_readiness(self):
        bad_rows = [
            [dict(udid='00000000-0000-0000-0000-000000000002', name=OWNER, state='Booted')],
            [dict(udid=DEVICE, name='Other owner', state='Booted')],
            [dict(udid=DEVICE, name=OWNER, state='Booted')] * 2,
        ]
        for rows in bad_rows:
            with self.subTest(rows=rows):
                client = AppleSimulators()
                original = subprocess.TimeoutExpired('boot', 60)
                inventories = [dict(devices={'runtime': [dict(udid=DEVICE, name=OWNER, state='Shutdown')]}),
                               dict(devices={'runtime': rows})]
                with patch.object(client, 'devices', side_effect=inventories), \
                        patch.object(client, 'invoke', side_effect=original) as invoke, \
                        patch('build_manager.apple_simulators.time.monotonic', return_value=0):
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:
                        client.boot(DEVICE, name=OWNER)
                self.assertIs(caught.exception, original)
                invoke.assert_called_once_with('boot', DEVICE)

    def test_late_booted_observation_cannot_bypass_the_deadline(self):
        client = AppleSimulators()
        original = subprocess.TimeoutExpired('boot', 60)
        clock = dict(now=0)
        def observed(*args, **kwargs):
            clock['now'] = 31
            return dict(state='Booted')
        with patch.object(client, 'matching', side_effect=[dict(state='Shutdown')]) as matching, \
                patch.object(client, 'invoke', side_effect=original) as invoke, \
                patch('build_manager.apple_simulators.time.monotonic', side_effect=lambda: clock['now']):
            def preflight_then_late(*args, **kwargs):
                if matching.call_count == 1:
                    return dict(state='Shutdown')
                return observed()
            matching.side_effect = preflight_then_late
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                client.boot(DEVICE, name=OWNER)
        self.assertIs(caught.exception, original)
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)
        invoke.assert_called_once_with('boot', DEVICE)

    def test_unnamed_initial_timeout_is_not_reconciled(self):
        client = AppleSimulators()
        original = subprocess.TimeoutExpired('boot', 60)
        with patch.object(client, 'invoke', side_effect=original) as invoke, \
                patch.object(client, 'devices') as devices:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                client.boot(DEVICE)
        self.assertIs(caught.exception, original)
        invoke.assert_called_once_with('boot', DEVICE)
        devices.assert_not_called()

    def test_missing_owned_device_is_rejected_before_initial_boot(self):
        client = AppleSimulators()
        with patch.object(client, 'matching', return_value=None), patch.object(client, 'invoke') as invoke:
            with self.assertRaises(ValueError):
                client.boot(DEVICE, name=OWNER)
        invoke.assert_not_called()


class SimulatorLeaseTests(unittest.TestCase):
    def test_timed_out_completion_is_rechecked_only_for_exact_booted_device(self):
        import subprocess
        from unittest.mock import patch
        for state in ('Booted', 'Booting', 'Shutdown'):
            with self.subTest(state=state):
                client = AppleSimulators(runner=lambda *a, **k: None)
                timeout = subprocess.TimeoutExpired('bootstatus', 180, output='already booted')
                with patch.object(client, 'devices', return_value={'devices': {'runtime': [dict(udid=DEVICE, state=state)]}}), \
                     patch.object(client, 'invoke', side_effect=['', timeout, '']) as invoke:
                    if state == 'Booted':
                        client.boot(DEVICE)
                        self.assertEqual([call.kwargs for call in invoke.call_args_list], [{}, {'timeout': 180}, {'timeout': 30}])
                    else:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            client.boot(DEVICE)
                    self.assertEqual(sum(call.args[0] == 'boot' for call in invoke.call_args_list), 1)

    def test_repeated_completion_timeout_never_implies_readiness(self):
        import subprocess
        from unittest.mock import patch
        client = AppleSimulators(runner=lambda *a, **k: None)
        timeout = subprocess.TimeoutExpired('bootstatus', 180)
        with patch.object(client, 'devices', return_value={'devices': {'runtime': [dict(udid=DEVICE, state='Booted')]}}), \
             patch.object(client, 'invoke', side_effect=['', timeout, timeout]):
            with self.assertRaises(subprocess.TimeoutExpired):
                client.boot(DEVICE)

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


class AppleToolDeadlineTests(unittest.TestCase):
    def test_unreapable_tool_fails_with_pid_without_unbounded_wait_or_retry(self):
        import subprocess
        from unittest.mock import Mock, patch
        process = Mock(pid=321, returncode=None)
        process.communicate.side_effect = [subprocess.TimeoutExpired('simctl', 60),
                                          subprocess.TimeoutExpired('simctl', 3)]
        with patch('build_manager.apple_simulators.subprocess.Popen', return_value=process) as spawn:
            with self.assertRaisesRegex(RuntimeError, 'PID 321.*unverified'):
                AppleSimulators().devices()
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual([call.kwargs['timeout'] for call in process.communicate.call_args_list], [60, 3])
        process.kill.assert_called_once()
        process.wait.assert_not_called()
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_real_timed_out_child_is_retired_and_never_reported_as_success(self):
        import subprocess
        import sys
        from build_manager.apple_simulators import _run_tool
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_tool([sys.executable, '-c', 'import time; time.sleep(20)'],
                      env=None, capture_output=True, text=True, timeout=.05)

    def test_actual_exit_code_and_output_are_preserved(self):
        import sys
        from build_manager.apple_simulators import _run_tool
        result = _run_tool([sys.executable, '-c', 'print("evidence"); raise SystemExit(7)'],
                           env=None, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), 'evidence')
