"""A second project's harmless processes exercise generic deployment controls."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox
from commonUtils.tests.qt_test_case import QtTestCase
from build_manager.deployment_commands import Command
from build_manager.deployment_commands_ui import CommandAction, CommandInventory, CommandPanel, CommandTarget


class ExamplePolicy:
    confirmation_marker = 'EXAMPLE_CONFIRM:'
    confirmation_title = 'Send prepared artifact?'
    hint = 'Example project'
    actions = (CommandAction('send', 'Send'), CommandAction('refresh', 'Refresh', inventory=True))

    def __init__(self, root, code):
        self.root, self.code = root, code

    def command(self, action, target):
        return Command((sys.executable, '-u', '-c', self.code), str(self.root))

    def logs(self, action):
        return self.root / 'logs'

    def inventory(self, text):
        data = json.loads(text)
        return CommandInventory(tuple(CommandTarget(d, d) for d in data['targets']), 'Example targets', tuple(data['errors']))


class DeploymentCommandUITests(QtTestCase):
    def test_split_utf8_prompt_waits_for_user_and_returns_only_their_answer(self):
        for answer, expected in ((QMessageBox.StandardButton.Yes, 'y'), (QMessageBox.StandardButton.No, 'n')):
            with self.subTest(expected=expected), self.temporary_directory() as directory:
                prompt = (ExamplePolicy.confirmation_marker + json.dumps('Send café?', ensure_ascii=False) + '\n').encode()
                # Split inside a UTF-8 code point as well as across the protocol marker.
                split = prompt.index('é'.encode()) + 1
                code = ('import sys,time\nprint("Prepared example artifact", flush=True)\n'
                        f'for part in ({prompt[:8]!r}, {prompt[8:split]!r}, {prompt[split:]!r}):\n'
                        ' sys.stdout.buffer.write(part);sys.stdout.flush();time.sleep(.02)\n'
                        'print("answer="+input(), flush=True)\n')
                panel = CommandPanel(ExamplePolicy(Path(directory), code))
                states = []; panel.busy_changed.connect(states.append)
                with patch('build_manager.deployment_commands_ui.QMessageBox.question', return_value=answer) as question:
                    panel.start('send')
                    self.wait_until(lambda: not panel.busy, timeout=10)
                question.assert_called_once()
                self.assertEqual(question.call_args.args[2], 'Send café?')
                self.assertIn('answer=' + expected, panel.output.toPlainText())
                self.assertNotIn(ExamplePolicy.confirmation_marker, panel.output.toPlainText())
                self.assertEqual(states, [True, False])
                self.assertTrue(panel.target.isEnabled())
                panel.close()

    def test_malformed_prompt_is_declined_without_opening_a_dialog(self):
        with self.temporary_directory() as directory:
            code = 'print("EXAMPLE_CONFIRM:{bad",flush=True);print("answer="+input(),flush=True)'
            panel = CommandPanel(ExamplePolicy(Path(directory), code))
            with patch('build_manager.deployment_commands_ui.QMessageBox.question') as question:
                panel.start('send')
                self.wait_until(lambda: not panel.busy, timeout=10)
            question.assert_not_called()
            self.assertIn('answer=n', panel.output.toPlainText())
            self.assertIn('Failed', panel.status.text())
            panel.close()

    def test_refresh_preserves_unavailable_target_and_errors_remain_failures(self):
        with self.temporary_directory() as directory:
            code = 'print(' + repr(json.dumps(dict(targets=[], errors=['discovery failed']))) + ')'
            panel = CommandPanel(ExamplePolicy(Path(directory), code))
            panel.update_targets([CommandTarget('Target one', 'one')]); panel.target.setCurrentIndex(1)
            panel.start('refresh'); self.wait_until(lambda: not panel.busy, timeout=10)
            self.assertEqual(panel.target.currentData(), 'one')
            panel.update_targets([])
            self.assertEqual(panel.target.currentText(), 'Target one (unavailable)')
            self.assertIn('discovery failed', panel.output.toPlainText())
            self.assertIn('Failed', panel.status.text())
            panel.update_targets([CommandTarget('Target one', 'one')])
            self.assertEqual(panel.target.currentText(), 'Target one')
            panel.close()

    def test_failed_start_and_external_busy_do_not_leave_controls_disabled(self):
        with self.temporary_directory() as directory:
            policy = ExamplePolicy(Path(directory), 'pass')
            panel = CommandPanel(policy)
            with patch.object(policy, 'command', return_value=Command(('/missing/example-python',), directory)):
                panel.set_external_busy(True)
                panel.start('send')
                self.assertFalse(panel.busy)
                self.assertFalse(panel.target.isEnabled())
                panel.set_external_busy(False)
                panel.start('send')
                self.wait_until(lambda: not panel.busy, timeout=10)
            self.assertEqual(panel.status.text(), 'Could not start')
            self.assertTrue(all(button.isEnabled() for button in panel.actions.values()))
            panel.close()

    def test_each_start_replaces_old_environment_overrides(self):
        with self.temporary_directory() as directory:
            policy = ExamplePolicy(Path(directory), 'pass')
            panel = CommandPanel(policy)
            for env in ({'EXAMPLE_OVERRIDE': 'old'}, {}):
                with patch.object(policy, 'command', return_value=Command((sys.executable, '-c', 'pass'), directory, env)):
                    panel.start('send'); self.wait_until(lambda: not panel.busy, timeout=10)
            self.assertFalse(panel.process.processEnvironment().contains('EXAMPLE_OVERRIDE'))
            panel.close()
