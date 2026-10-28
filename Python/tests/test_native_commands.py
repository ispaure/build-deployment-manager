"""Native preparation preserves command outcomes and always retires owned children."""
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from build_manager import native_commands as mobile_processes


class MobileProcessTests(unittest.TestCase):
    def test_completed_command_retires_group_after_parent_exit(self):
        process = Mock()
        process.wait.return_value = 0
        with patch.object(mobile_processes.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(mobile_processes, 'stop_process') as stop:
            mobile_processes.command(['native-tool', 'prepare'], '/project', timeout=42)
        spawn.assert_called_once_with(['native-tool', 'prepare'], cwd='/project', start_new_session=True)
        process.wait.assert_called_once_with(timeout=42)
        stop.assert_called_once_with(process)

    def test_failed_command_preserves_exit_error_and_retires_group(self):
        process = Mock()
        process.wait.return_value = 7
        with patch.object(mobile_processes.subprocess, 'Popen', return_value=process), \
                patch.object(mobile_processes, 'stop_process') as stop:
            with self.assertRaisesRegex(RuntimeError, 'Command failed: 7'):
                mobile_processes.command(['native-tool'], '/project')
        stop.assert_called_once_with(process)

    def test_timeout_and_interruption_preserve_error_after_cleanup(self):
        for error in (subprocess.TimeoutExpired(['native-tool'], 42), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                process = Mock()
                process.wait.side_effect = error
                with patch.object(mobile_processes.subprocess, 'Popen', return_value=process), \
                        patch.object(mobile_processes, 'stop_process') as stop:
                    with self.assertRaises(type(error)) as caught:
                        mobile_processes.command(['native-tool'], '/project', timeout=42)
                self.assertIs(caught.exception, error)
                stop.assert_called_once_with(process)

    def test_cleanup_failure_is_reported(self):
        process = Mock()
        process.wait.return_value = 0
        with patch.object(mobile_processes.subprocess, 'Popen', return_value=process), \
                patch.object(mobile_processes, 'stop_process', side_effect=PermissionError('cleanup denied')):
            with self.assertRaisesRegex(PermissionError, 'cleanup denied'):
                mobile_processes.command(['native-tool'], '/project')

    @unittest.skipIf(os.name == 'nt', 'Native preparation helper owns POSIX groups')
    def test_real_timeout_reaps_owned_child(self):
        spawn = subprocess.Popen
        children = []

        def capture(*args, **kwargs):
            process = spawn(*args, **kwargs)
            children.append(process)
            return process

        try:
            with patch.object(mobile_processes.subprocess, 'Popen', side_effect=capture):
                with self.assertRaises(subprocess.TimeoutExpired):
                    mobile_processes.command([sys.executable, '-c', 'import time; time.sleep(30)'],
                                             os.getcwd(), timeout=.1)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
        finally:
            for process in children:
                mobile_processes.stop_process(process)


if __name__ == '__main__':
    unittest.main()
