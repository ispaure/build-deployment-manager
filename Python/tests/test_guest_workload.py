"""Guest lifecycle failure injection; transport/native acceptance remains separate."""
import json
import io
import subprocess
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock

from build_manager import Phase, Plan
from build_manager.guest_workload import run_workload, prepare_windows, source_zip, LinuxSession, WindowsSession, GuestResultLifecycle


class Session:
    vm, token, workspace = 'vm', 'a' * 32, '/owned'
    python, plan_path, reports, evidence = '/python', '/plan.json', '/reports', 'result.json'
    def __init__(self, failure='', status='passed', identity=None):
        self.calls, self.failure, self.status, self.identity = [], failure, status, identity
    def event(self, name):
        self.calls.append(name)
        if name == self.failure: raise RuntimeError(name)
    def stage(self, *args): self.event('stage')
    def exists(self): self.event('exists'); return True
    def prepare_environment(self, *args): self.event('environment')
    def execute(self, *args): self.event('execute'); return 0
    def write(self, data): self.event('write'); self.plan = json.loads(data)
    def collect(self, destination):
        self.event('collect'); destination.mkdir()
        if self.status != 'missing':
            (destination / 'result.json').write_text(json.dumps(dict(source=self.identity or {'revision': 'one'},
                backend='fixture', status=self.status, plan_identity=__import__('build_manager').Plan.from_data(self.plan).identity if hasattr(self, 'plan') else '',
                phases=[dict(id='check', status='passed')])) )
    def cleanup(self): self.event('cleanup')


class GuestWorkloadTests(unittest.TestCase):
    def run_fixture(self, session, cancel=False, wrong_plan=False):
        with TemporaryDirectory() as folder:
            event = Event()
            if cancel: event.set()
            plan = lambda s: Plan('Example', 'Test', {'revision': 'wrong' if wrong_plan else 'one'},
                (Phase('check', ('python', '-V'), '/owned/source'),), '/owned/workspace', backend='fixture')
            result = run_workload(session, snapshot=folder, members=[], directory=Path(folder) / 'results',
                source={'revision': 'one'}, backend='fixture', prepare=lambda s, execute: s.event('prepare'),
                make_plan=plan, environment={}, cancelled=event)
            self.assertEqual(json.loads((Path(folder) / 'results/result.json').read_text()), result)
            return result

    def test_complete_lifecycle_and_cancellation_before_guest_access(self):
        session = Session()
        self.assertEqual(self.run_fixture(session)['status'], 'passed')
        self.assertEqual(session.calls, ['stage', 'environment', 'prepare', 'write', 'execute', 'exists', 'collect', 'cleanup'])
        session = Session()
        self.assertEqual(self.run_fixture(session, cancel=True)['status'], 'cancelled')
        self.assertEqual(session.calls, [])

    def test_unexpected_callback_error_is_recorded_and_cleanup_still_runs(self):
        session = Session()
        session.prepare_environment = Mock(side_effect=TypeError('invalid callback data'))
        result = self.run_fixture(session)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'invalid callback data')
        self.assertIn('cleanup', session.calls)
        for callback in ('collect', 'cleanup', 'exists'):
            with self.subTest(callback=callback):
                session = Session()
                setattr(session, callback, Mock(side_effect=TypeError('invalid callback data')))
                result = self.run_fixture(session)
                self.assertEqual(result['status'], 'failed')
                if callback != 'cleanup':
                    self.assertTrue(result['guest_workspace_preserved_for_recovery'])

    def test_windows_cleanup_receipt_distinguishes_operation_from_tools(self):
        class WindowsFixture(Session, WindowsSession):
            operation = 'a' * 32
        result = self.run_fixture(WindowsFixture())
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['guest_operation_removed'])
        self.assertTrue(result['public_tool_workspace_retained'])
        self.assertNotIn('guest_workspace_removed', result)

    def test_failures_never_turn_green_or_repeat_work(self):
        for failure in ('stage', 'environment', 'prepare', 'write', 'execute', 'collect', 'cleanup', 'exists'):
            with self.subTest(failure=failure):
                session = Session(failure=failure)
                result = self.run_fixture(session)
                self.assertEqual(result['status'], 'failed')
                self.assertLessEqual(session.calls.count('execute'), 1)
                if failure in {'collect', 'exists'}:
                    self.assertNotIn('cleanup', session.calls)
                    self.assertTrue(result['guest_workspace_preserved_for_recovery'])
                if failure in {'stage', 'environment', 'prepare', 'write'}:
                    self.assertNotIn('execute', session.calls)

    def test_missing_mismatched_or_failed_evidence_cannot_pass(self):
        for session in (Session(status='missing'), Session(status='failed'), Session(identity={'revision': 'other'})):
            with self.subTest(status=session.status, identity=session.identity):
                result = self.run_fixture(session)
                self.assertEqual(result['status'], 'failed')
                self.assertIn('retrieval_error', result)
        session = Session()
        self.assertEqual(self.run_fixture(session, wrong_plan=True)['status'], 'failed')
        self.assertNotIn('execute', session.calls)

    def test_windows_preparation_preserves_failed_receipt_and_rejects_replay(self):
        client = Mock()
        client.start.return_value = {'uuid': 'vm', 'status': 'stopped'}
        client.powershell.side_effect = RuntimeError('transport lost')
        tools = {k: {'url': 'https://github.com/example/' + k + '.zip', 'sha256': 'a'*64} for k in ('uv', 'git')}
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'prepared.json'
            options = dict(python='3.12.2', guest_architecture='ARM64', python_architecture='x86_64')
            with self.assertRaises(RuntimeError): prepare_windows(client, 'vm', path, tools, **options)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['status'], 'failed'); self.assertFalse(receipt['tests_run'])
            with self.assertRaises(ValueError): prepare_windows(client, 'vm', path, tools, **options)
            self.assertEqual(client.start.call_count, 1)

    def test_source_members_and_workspaces_cannot_escape(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): source_zip(Path(folder), ['../secret'])
        with self.assertRaises(ValueError): LinuxSession(Mock(), 'vm', 0, 0)
        with self.assertRaises(ValueError): LinuxSession(Mock(), 'vm', 1000, 1000, token='../escape')
        with self.assertRaises(ValueError): WindowsSession(Mock(), {'status': 'failed'})

    def test_source_archive_preserves_empty_git_metadata_directories(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'target'
            source.mkdir()
            subprocess.run(['git', 'init', '--quiet', str(source)], check=True)
            payload = source_zip(source, ['.git'])
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                archive.extractall(target)
            self.assertTrue((target / '.git/refs').is_dir())
            subprocess.run(['git', '-C', str(target), 'rev-parse', '--git-dir'],
                           check=True, capture_output=True)

    def test_windows_environments_are_per_operation(self):
        prepared = dict(status='prepared', vm='vm', token='b'*32, workspace='C:\\owned\\'+'b'*32, python='C:\\owned\\'+'b'*32+'\\environment\\Scripts\\python.exe')
        one, two = WindowsSession(Mock(), prepared), WindowsSession(Mock(), prepared)
        self.assertNotEqual(one.python, two.python)
        self.assertNotEqual(one.source, two.source)
        execute = Mock()
        one.prepare_environment(execute, {})
        self.assertEqual(execute.call_args.args[0][1:3], ['-m', 'venv'])

    def test_guest_receipts_require_the_actual_plan_and_all_required_steps(self):
        plan = Plan('Fixture', 'Test', {}, (Phase('required', ('python', '-V'), '/source'),), '/workspace', backend='fixture')
        for change in ({'plan_identity': 'wrong'}, {'phases': []}, {'phases': [dict(id='required', status='skipped')]},
                       {'phases': [dict(id='required', status='passed')]*2}, {'phases': ['invalid']}):
            with self.subTest(change=change), TemporaryDirectory() as folder:
                root = Path(folder)
                report = dict(source={}, backend='fixture', status='passed', plan_identity=plan.identity,
                              phases=[dict(id='required', status='passed')])
                report.update(change)
                path = root/'evidence.json'; path.write_text(json.dumps(report))
                result = dict(source={}, status='passed')
                lifecycle = GuestResultLifecycle(result, root, 'fixture', 'guest', expected_plan=plan)
                cleanup = Mock()
                lifecycle.collect(lambda: None, path, cleanup)
                self.assertEqual(result['status'], 'failed')
                cleanup.assert_called_once()

    def test_windows_receipt_cannot_select_an_unowned_interpreter(self):
        with self.assertRaises(ValueError):
            WindowsSession(Mock(), dict(status='prepared', vm='vm', token='b'*32,
                workspace='C:\\owned\\'+'b'*32, python='C:\\personal\\python.exe'))
