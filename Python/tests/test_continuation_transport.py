"""Mocked GUI process transport and internal CLI preserve the selected retry policy."""
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ContinuationTransportTests(unittest.TestCase):
    def session(self):
        # Exercise the real transport method without starting Qt or a process.
        qt = ModuleType('PySide6.QtCore')
        for name in ('QObject', 'QElapsedTimer', 'QProcess', 'QTimer'):
            setattr(qt, name, object)
        source = Path(__file__).resolve().parents[1] / 'build_manager/run_session.py'
        spec = importlib.util.spec_from_file_location('build_manager._mock_session', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'PySide6': ModuleType('PySide6'), 'PySide6.QtCore': qt}):
            spec.loader.exec_module(module)
        session = object.__new__(module.RunSession)
        session.events = SimpleNamespace(buffer='')
        session.process = Mock()
        return session

    def test_continue_ready_transports_policy_and_exact_selected_approval(self):
        session = self.session()
        permission = SimpleNamespace(step='ios-ready', identity='a' * 64)
        session.launch('project-python', Path('/tmp/plan.json'), Path('/tmp/run'),
                       resume=True, confirmed=True, approvals=(permission,), retry_failed=False)
        interpreter, args = session.process.start.call_args.args
        self.assertEqual(interpreter, 'project-python')
        self.assertIn('--resume', args)
        self.assertIn('--no-retry-failed', args)
        self.assertEqual(args[-4:], ['--approve-step', 'ios-ready', '--approval-identity', 'ios-ready=' + 'a' * 64])

    def test_explicit_retry_default_remains_and_fresh_run_cannot_preserve_failures(self):
        session = self.session()
        session.launch('python', Path('/tmp/plan.json'), Path('/tmp/run'), resume=True)
        self.assertNotIn('--no-retry-failed', session.process.start.call_args.args[1])
        session.process.reset_mock()
        with self.assertRaisesRegex(ValueError, 'retained run'):
            session.launch('python', Path('/tmp/plan.json'), Path('/tmp/run'), retry_failed=False)
        session.process.start.assert_not_called()

    def test_internal_cli_passes_preserve_failed_to_executor_without_running_work(self):
        from build_manager import __main__ as cli
        with patch.object(sys, 'argv', ['build_manager', '/tmp/plan.json', '--output', '/tmp/run',
                '--resume', '--no-retry-failed']), patch.object(cli.Plan, 'load'), \
                patch.object(cli, 'Executor') as executor, patch.object(cli.signal, 'signal'), redirect_stdout(StringIO()):
            executor.return_value.run.return_value = {'status': 'failed'}
            self.assertEqual(cli.main(), 1)
        self.assertFalse(executor.return_value.run.call_args.kwargs['retry_failed'])
        self.assertTrue(executor.return_value.run.call_args.kwargs['resume'])
