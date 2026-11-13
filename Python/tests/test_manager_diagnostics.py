"""Portable manager-session recovery in an isolated registry."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import textwrap
import threading
import unittest
from unittest.mock import Mock, patch

from build_manager import Executor, Phase, Plan
from build_manager.manager_diagnostics import DiagnosticStore, DiagnosticUnavailable


_SOURCE_ROOT = Path(__file__).resolve().parents[1]
_RECORD_LIMIT = 64 * 1024
_STORE_CAPACITY = 32


class ManagerDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.registry = self.root / 'registry'
        self.registry.mkdir()
        self.store = DiagnosticStore(self.registry)

    def start(self, store=None):
        session = (store or self.store).start()
        self.addCleanup(session.close)
        return session

    def run_child(self, source, *arguments):
        bootstrap = f'import sys\nsys.path.insert(0, {str(_SOURCE_ROOT)!r})\n'
        return subprocess.run([sys.executable, '-I', '-c', bootstrap + textwrap.dedent(source),
                               str(self.registry), *map(str, arguments)], capture_output=True,
                              text=True, encoding='utf-8', timeout=15, check=False)

    def record_path(self, record_id):
        matches = []
        for path in self.registry.rglob('*.json'):
            if path.is_file() and not path.is_symlink():
                try:
                    data = json.loads(path.read_bytes())
                except (UnicodeError, ValueError):
                    continue
                if isinstance(data, dict) and data.get('id') == record_id:
                    matches.append(path)
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_active_peer_is_invisible_and_clean_shutdown_removes_its_marker(self):
        first = self.start()
        peer_store = DiagnosticStore(self.registry)
        peer = self.start(peer_store)
        self.assertNotEqual(first.id, peer.id)
        self.assertEqual(peer_store.pending(), [])
        self.assertEqual(self.store.pending(), [])
        with self.assertRaises(DiagnosticUnavailable):
            peer_store.dismiss(first.id)

        first.close()
        with self.assertRaises(DiagnosticUnavailable):
            peer_store.read(first.id)
        peer.close()
        self.assertEqual(self.store.pending(), [])

    def test_abrupt_owned_process_exit_preserves_the_last_valid_run_bytes(self):
        run_directory = self.registry / 'runs' / 'fixture-run'
        plan = Plan('Disposable fixture', 'Verify', {}, (
            Phase('fixture', (sys.executable, '-c', 'print("retained run log")'), str(self.root)),
        ), str(self.root / 'workspace'))
        report = Executor().run(plan, run_directory)
        self.assertEqual(report['status'], 'passed')
        plan_path = run_directory / 'plan.json'
        report_path = run_directory / 'result.json'
        retained = {path: path.read_bytes() for path in (plan_path, report_path)}
        active_peer = self.start()

        child = self.run_child('''
            import os
            from build_manager.manager_diagnostics import DiagnosticStore
            session = DiagnosticStore(sys.argv[1]).start()
            print(session.id, flush=True)
            os._exit(27)
        ''')
        self.assertEqual(child.returncode, 27, child.stderr)
        ended_id = child.stdout.strip()
        next_launch = DiagnosticStore(self.registry)
        reports = next_launch.pending()
        self.assertEqual([record['id'] for record in reports], [ended_id])
        self.assertNotEqual(ended_id, active_peer.id)
        self.assertEqual(reports[0]['state'], 'ended')
        self.assertFalse(reports[0].get('exception'))
        self.assertIn('unexpected', reports[0]['message'].lower())
        self.assertNotIn('failed run', reports[0]['message'].lower())

        next_launch.dismiss(ended_id)
        self.assertEqual(next_launch.pending(), [])
        for path, original in retained.items():
            self.assertEqual(path.read_bytes(), original)

    @patch.dict(os.environ, {'FIXTURE_TOKEN': 'fixture-manager-private-secret'}, clear=True)
    def test_exception_record_filters_message_and_keeps_stack_without_source_or_locals(self):
        def raise_fixture_exception():
            fixture_private_local = 'fixture-unreported-local'
            raise ValueError('Fixture exception at /Users/fixture-private-home/output; fixture-manager-private-secret')

        session = self.start()
        try:
            raise_fixture_exception()
        except ValueError:
            session.record_exception(*sys.exc_info())
        self.assertEqual(DiagnosticStore(self.registry).pending(), [])
        session.close()

        [record] = DiagnosticStore(self.registry).pending()
        self.assertEqual(record['id'], session.id)
        self.assertEqual(record['state'], 'error')
        self.assertEqual(record['exception'], 'ValueError')
        self.assertIn('Fixture exception', record['message'])
        self.assertIn('raise_fixture_exception', str(record['stack']))
        serialized = self.record_path(session.id).read_text(encoding='utf-8')
        for private in ('fixture-private-home', 'fixture-manager-private-secret', 'fixture-unreported-local',
                        'fixture_private_local', 'raise ValueError', str(Path(__file__).resolve())):
            self.assertNotIn(private, serialized)

    def test_python_main_exception_hook_persists_a_disposable_child_failure(self):
        child = self.run_child('''
            from build_manager.manager_diagnostics import DiagnosticStore
            session = DiagnosticStore(sys.argv[1]).start()
            session.install_hooks()
            raise RuntimeError('Fixture unhandled main exception')
        ''')
        self.assertNotEqual(child.returncode, 0)
        self.assertIn('Fixture unhandled main exception', child.stderr)
        [record] = self.store.pending()
        self.assertEqual(record['exception'], 'RuntimeError')
        self.assertIn('Fixture unhandled main exception', record['message'])

    def test_thread_exception_hook_delegates_and_restores_original_hooks(self):
        def failing_worker():
            raise LookupError('Fixture unhandled thread exception')

        session = self.start()
        main_hook = Mock()
        thread_hook = Mock()
        with patch.object(sys, 'excepthook', main_hook), patch.object(threading, 'excepthook', thread_hook):
            session.install_hooks()
            try:
                worker = threading.Thread(target=failing_worker, name='fixture-worker')
                worker.start()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                thread_hook.assert_called_once()
            finally:
                session.restore_hooks()
            self.assertIs(sys.excepthook, main_hook)
            self.assertIs(threading.excepthook, thread_hook)
        session.close()
        [record] = self.store.pending()
        self.assertEqual(record['exception'], 'LookupError')
        self.assertIn('Fixture unhandled thread exception', record['message'])

    def test_in_flight_thread_hook_delegates_after_the_session_closes(self):
        entered, release = threading.Event(), threading.Event()
        session = self.start()
        main_hook, thread_hook = Mock(), Mock()

        def blocked_record(*args):
            entered.set()
            release.wait(5)

        def failing_worker():
            raise LookupError('Fixture in-flight exception')

        with (patch.object(sys, 'excepthook', main_hook), patch.object(threading, 'excepthook', thread_hook),
              patch.object(session, 'record_exception', side_effect=blocked_record)):
            session.install_hooks()
            worker = threading.Thread(target=failing_worker, name='fixture-in-flight-hook')
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                session.close()
                self.assertIs(threading.excepthook, thread_hook)
            finally:
                release.set()
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            thread_hook.assert_called_once()
            self.assertIs(thread_hook.call_args.args[0].thread, worker)
            main_hook.assert_not_called()

    def test_hooks_delegate_even_if_the_recorder_raises(self):
        session = self.start()
        main_hook, thread_hook = Mock(), Mock()
        original_error = LookupError('Fixture original error')
        thread_args = threading.ExceptHookArgs((LookupError, original_error, None, threading.current_thread()))
        with (patch.object(sys, 'excepthook', main_hook), patch.object(threading, 'excepthook', thread_hook),
              patch.object(session, 'record_exception', side_effect=RuntimeError('Fixture recorder failure'))):
            session.install_hooks()
            try:
                with self.assertRaises(RuntimeError):
                    sys.excepthook(LookupError, original_error, None)
                with self.assertRaises(RuntimeError):
                    threading.excepthook(thread_args)
            finally:
                session.restore_hooks()
        main_hook.assert_called_once_with(LookupError, original_error, None)
        thread_hook.assert_called_once_with(thread_args)

    def test_unformattable_exception_persists_generic_error_without_touching_run(self):
        class UnformattableError(Exception):
            def __str__(self):
                raise ValueError('fixture-private-formatting-error')

        run_directory = self.registry / 'runs' / 'fixture-unformattable-error'
        plan = Plan('Disposable fixture', 'Verify', {}, (
            Phase('fixture', (sys.executable, '-c', 'print("retained run log")'), str(self.root)),
        ), str(self.root / 'workspace'))
        self.assertEqual(Executor().run(plan, run_directory)['status'], 'passed')
        retained = {path: path.read_bytes() for path in (run_directory / 'plan.json', run_directory / 'result.json')}
        session = self.start()
        try:
            raise UnformattableError('fixture-private-original-error')
        except UnformattableError:
            session.record_exception(*sys.exc_info())
        session.close()

        [record] = self.store.pending()
        self.assertEqual(record['exception'], 'Exception')
        self.assertIn('could not be formatted', record['message'])
        self.assertNotIn('fixture-private-', self.record_path(session.id).read_text(encoding='utf-8'))
        for path, original in retained.items():
            self.assertEqual(path.read_bytes(), original)

    def test_full_store_preserves_saved_report_until_explicit_dismissal(self):
        saved = self.start()
        saved.record_exception(ValueError, ValueError('Fixture manager error'), None)
        saved.close()
        active = [self.start() for _ in range(_STORE_CAPACITY - 1)]
        paths = [self.record_path(session.id) for session in [saved, *active]]
        before = {path: path.read_bytes() for path in paths}
        with self.assertRaises(DiagnosticUnavailable):
            DiagnosticStore(self.registry).start()
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertLessEqual(sum(map(len, before.values())), 2 * 1024 * 1024)
        self.assertEqual([row['id'] for row in self.store.pending()], [saved.id])

        self.store.dismiss(saved.id)
        replacement = self.start()
        self.assertNotIn(replacement.id, {session.id for session in [saved, *active]})
        self.assertEqual(self.store.pending(), [])

    def test_oversized_error_message_keeps_a_valid_bounded_record(self):
        session = self.start()
        message = 'Fixture long exception ' + ('片' * _RECORD_LIMIT)
        session.record_exception(ValueError, ValueError(message), None)
        session.close()
        [record] = self.store.pending()
        self.assertEqual(record['exception'], 'ValueError')
        self.assertLessEqual(self.record_path(record['id']).stat().st_size, _RECORD_LIMIT)

    def test_malformed_oversized_and_foreign_records_cannot_be_read_or_dismissed(self):
        session = self.start()
        session.record_exception(ValueError, ValueError('Fixture manager error'), None)
        session.close()
        record = self.store.read(session.id)
        path = self.record_path(session.id)

        invalid_records = {
            'malformed JSON': b'{"broken":',
            'oversized record': b' ' * (_RECORD_LIMIT + 1),
        }
        for field, value in (('kind', 'foreign-record'), ('id', 'foreign-id'), ('state', ['active']),
                             ('schema', True), ('unrecognized_field', 'fixture-private-extra-field')):
            invalid_records[field] = json.dumps(dict(record, **{field: value})).encode()

        for label, invalid in invalid_records.items():
            with self.subTest(record=label):
                path.write_bytes(invalid)
                reader = DiagnosticStore(self.registry)
                self.assertEqual(reader.pending(), [])
                self.assertTrue(reader.warning)
                with self.assertRaises(DiagnosticUnavailable):
                    self.store.read(session.id)
                with self.assertRaises(DiagnosticUnavailable):
                    self.store.dismiss(session.id)
                self.assertEqual(path.read_bytes(), invalid)

    def test_linked_record_cannot_be_read_or_dismissed(self):
        session = self.start()
        session.record_exception(ValueError, ValueError('Fixture manager error'), None)
        session.close()
        path = self.record_path(session.id)
        original = path.read_bytes()
        outside = self.root / 'outside.json'
        path.rename(outside)
        try:
            path.symlink_to(outside)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f'Symlinks unavailable: {error}')

        self.assertEqual(DiagnosticStore(self.registry).pending(), [])
        with self.assertRaises(DiagnosticUnavailable):
            self.store.read(session.id)
        with self.assertRaises(DiagnosticUnavailable):
            self.store.dismiss(session.id)
        self.assertTrue(path.is_symlink())
        self.assertEqual(outside.read_bytes(), original)

    def test_symlink_registry_root_is_rejected_without_writing_to_target(self):
        outside = self.root / 'outside-registry'
        outside.mkdir()
        linked_registry = self.root / 'linked-registry'
        try:
            linked_registry.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f'Symlinks unavailable: {error}')

        linked_store = DiagnosticStore(linked_registry)
        with self.assertRaises(DiagnosticUnavailable):
            linked_store.start()
        with self.assertRaises(DiagnosticUnavailable):
            linked_store.pending()
        self.assertEqual(list(outside.iterdir()), [])

    def test_headless_modules_never_import_qt_or_project_adapters(self):
        child = self.run_child('''
            import importlib.abc

            class BlockUIAndProjectImports(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] in {'PySide6', 'PyQt6', 'PyQt5', 'mobile', 'features'}:
                        raise AssertionError('Unexpected import: ' + fullname)

            sys.meta_path.insert(0, BlockUIAndProjectImports())
            from build_manager import diagnostics, manager_diagnostics
            assert diagnostics.diagnose(None, {}).category == 'none'
            manager_diagnostics.DiagnosticStore(sys.argv[1]).start().close()
        ''')
        self.assertEqual(child.returncode, 0, child.stderr)
