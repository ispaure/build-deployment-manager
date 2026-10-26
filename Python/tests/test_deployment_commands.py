"""Compatibility sequences inherit terminal prompts and never hide earlier failures."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.deployment_commands import Command, CommandStep, confirmation_input, run_sequence


class DeploymentCommandTests(unittest.TestCase):
    def test_actual_sequence_keeps_order_and_failure_after_continuing(self):
        with TemporaryDirectory() as directory:
            record = Path(directory) / 'order'
            def step(label, code):
                body = f'from pathlib import Path;p=Path({str(record)!r});p.open("a").write({label!r});raise SystemExit({code})'
                return CommandStep(label, Command((sys.executable, '-c', body), directory))
            steps = (step('first', 0), step('failed', 7), step('last', 0))
            decisions = []
            failed = run_sequence(steps, continue_after_failure=lambda step, code: decisions.append((step.label, code)) or True)
            self.assertEqual([step.label for step in failed], ['failed'])
            self.assertEqual(decisions, [('failed', 7)])
            self.assertEqual(record.read_text(), 'firstfailedlast')

    def test_declining_failure_stops_and_input_is_inherited(self):
        steps = tuple(CommandStep(name, Command((name,), '/fixture')) for name in ('first', 'last'))
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertEqual(run_sequence(steps), (steps[0],))
        run.assert_called_once_with(['first'], cwd=Path('/fixture'), env=None)
        self.assertNotIn('stdin', run.call_args.kwargs)

    def test_actual_sequence_child_inherits_interactive_input(self):
        with TemporaryDirectory() as directory:
            code = ('import sys; from build_manager.deployment_commands import Command, CommandStep, run_sequence; '
                    'step=CommandStep("interactive", Command((sys.executable,"-c",'
                    '\'print("answer="+input("Ship? "),flush=True)\'),sys.argv[1])); '
                    'assert not run_sequence((step,))')
            result = subprocess.run([sys.executable, '-c', code, directory], input='n\n',
                                    capture_output=True, text=True, check=True)
        self.assertIn('answer=n', result.stdout)

    def test_confirmation_retains_caller_marker_and_literal_answer(self):
        stream = io.StringIO()
        with redirect_stdout(stream), patch('builtins.input', return_value='n'):
            self.assertEqual(confirmation_input('Send the prepared artifact?', marker='EXAMPLE_CONFIRM:'), 'n')
        self.assertEqual(stream.getvalue(), '\nEXAMPLE_CONFIRM:' + json.dumps('Send the prepared artifact?') + '\n')

    def test_headless_import_does_not_load_qt_or_a_project(self):
        code = ('import sys; from build_manager import deployment_commands; '
                'assert not any(n.startswith(("PySide6", "mobile_build", "Scripts")) for n in sys.modules)')
        subprocess.run([sys.executable, '-c', code], check=True)
