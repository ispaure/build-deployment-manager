"""Cleanup diagnostics cannot mask, repeat or pre-delay original fixture cleanup."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import owned_cleanup


class OwnedCleanupTests(unittest.TestCase):
    def test_success_has_no_evidence_queries_and_calls_cleanup_once(self):
        temporary = SimpleNamespace(cleanup=Mock(return_value='removed'))
        with patch.object(owned_cleanup, '_diagnose_failure') as diagnostic, \
                patch.object(owned_cleanup, '_owned_executable') as guard:
            self.assertEqual(owned_cleanup.cleanup_private_interpreter(temporary), 'removed')
        temporary.cleanup.assert_called_once_with()
        diagnostic.assert_not_called(); guard.assert_not_called()

    def test_original_error_survives_metadata_timeout_and_bad_serialization(self):
        for result in ({'resource_owners': {'query_error': 5}}, object(), TimeoutError(),
                       json.JSONDecodeError('invalid', '', 0)):
            with self.subTest(result=type(result).__name__):
                error = PermissionError(13, 'denied', '/fixture/.venv/Scripts/python.exe')
                error.winerror = 5
                temporary = SimpleNamespace(name='/fixture', cleanup=Mock(side_effect=error))
                diagnostic = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
                with patch.object(owned_cleanup, 'os', SimpleNamespace(name='nt')), \
                        patch.object(owned_cleanup, '_owned_executable', return_value=True), \
                        patch.object(owned_cleanup, '_diagnose_failure', diagnostic):
                    with self.assertRaises(PermissionError) as caught:
                        owned_cleanup.cleanup_private_interpreter(temporary)
                self.assertIs(caught.exception, error)
                temporary.cleanup.assert_called_once_with()
                diagnostic.assert_called_once_with(temporary.name, error.filename)
                self.assertIn('Private interpreter cleanup evidence:', error.__notes__[0])
                json.loads(error.__notes__[0].split(': ', 1)[1])

    def test_other_platforms_errors_and_foreign_paths_do_not_query_owners(self):
        for system, code, owned in [('posix', 5, True), ('nt', 32, True), ('nt', 5, False)]:
            with self.subTest(system=system, code=code, owned=owned):
                error = PermissionError(13, 'denied', '/unowned/python.exe'); error.winerror = code
                temporary = SimpleNamespace(name='/fixture', cleanup=Mock(side_effect=error))
                with patch.object(owned_cleanup, 'os', SimpleNamespace(name=system)), \
                        patch.object(owned_cleanup, '_owned_executable', return_value=owned), \
                        patch.object(owned_cleanup, '_diagnose_failure') as diagnostic:
                    with self.assertRaises(PermissionError) as caught:
                        owned_cleanup.cleanup_private_interpreter(temporary)
                self.assertIs(caught.exception, error)
                temporary.cleanup.assert_called_once_with()
                diagnostic.assert_not_called()

    def test_resource_query_errors_are_not_reported_as_empty_owners(self):
        library = Mock()
        library.RmStartSession.return_value = library.RmRegisterResources.return_value = 0
        for second_status in (5, 234):
            with self.subTest(second_status=second_status):
                calls = []
                def get_list(session, needed, count, rows, reasons):
                    calls.append(rows)
                    needed._obj.value = 1
                    return 234 if len(calls) == 1 else second_status
                library.RmGetList.side_effect = get_list
                result = owned_cleanup._resource_owners('fixture', library)
                self.assertEqual(result['query_error'], second_status)
                self.assertNotIn('owners', result)
        self.assertEqual(library.RmEndSession.call_count, 2)

    def test_only_exact_owned_nonlinked_executable_is_eligible(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / '.venv/Scripts/python.exe'
            target.parent.mkdir(parents=True); target.write_bytes(b'fixture')
            self.assertTrue(owned_cleanup._owned_executable(root, target))
            self.assertFalse(owned_cleanup._owned_executable(root, root / 'other.exe'))
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=0, st_file_attributes=0x400)):
                self.assertFalse(owned_cleanup._owned_executable(root, target))

    def test_diagnostic_child_has_a_deadline_and_does_not_forward_stderr(self):
        with patch.object(owned_cleanup.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='private output')) as run:
            result = owned_cleanup._diagnose_failure('/fixture', '/fixture/.venv/Scripts/python.exe')
        self.assertEqual(result, {'error': 'diagnostic_child_failed', 'exit_code': 1})
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertEqual(run.call_args.args[0][1:3], ['-I', '-B'])

    def test_unavailable_and_oversize_hashes_remain_explicitly_unknown(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'python.exe'
            self.assertEqual(owned_cleanup._executable_hash(target)['error'], 'FileNotFoundError')
            with target.open('wb') as stream:
                stream.truncate(16 * 1024 * 1024 + 1)
            self.assertEqual(owned_cleanup._executable_hash(target), {'error': 'size_limit'})

    def test_failure_metadata_distinguishes_guest_os_from_python_build(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / '.venv/Scripts/python.exe'
            target.parent.mkdir(parents=True); target.write_bytes(b'fixture')
            with patch.object(owned_cleanup.platform, 'win32_ver', return_value=('11', '26300', '', '')), \
                    patch.object(owned_cleanup.platform, 'machine', return_value='ARM64'), \
                    patch.object(owned_cleanup, '_executable_hash', return_value={'sha256': 'fixture'}), \
                    patch.object(owned_cleanup, '_resource_owners', return_value={'query_error': 5}):
                evidence = owned_cleanup._collect_failure(root, target)
            self.assertEqual(evidence['windows_version'][:2], ('11', '26300'))
            self.assertEqual(evidence['machine'], 'ARM64')
            self.assertIn('compiler', evidence)
            self.assertIn('python_bits', evidence)
            self.assertEqual(evidence['resource_owners'], {'query_error': 5})
