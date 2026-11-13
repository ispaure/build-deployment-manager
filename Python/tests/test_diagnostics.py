"""Portable diagnosis, share-text and retained-log contracts."""
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan
from build_manager.diagnostics import diagnose, format_diagnostics, read_log
from build_manager.redaction import ShareRedactor


_LOG_LIMIT = 256 * 1024
_COPY_LIMIT = 16 * 1024
_WORKSPACE = '/private/fixture/diagnostic-workspace'


def fixture_plan():
    return Plan('Diagnostic fixture', 'Verify and deliver', {'hidden': 'source-dictionary-value'}, (
        Phase('unit', ('fixture-tool', '--password', 'argv-private-value'), _WORKSPACE,
              environment={'LOCAL_CONFIG': 'environment-dictionary-value'}, label='Unit tests'),
        Phase('build', ('fixture-tool', 'build'), _WORKSPACE, dependencies=('unit',),
              effect='build', kind='build', label='Build package'),
        Phase('blocked-delivery', ('fixture-tool', 'deploy'), _WORKSPACE, dependencies=('build',),
              effect='deploy', kind='deploy', label='Blocked delivery'),
        Phase('completed-delivery', ('fixture-tool', 'deploy'), _WORKSPACE,
              effect='deploy', kind='deploy', label='Completed delivery'),
        Phase('uncertain-delivery', ('fixture-tool', 'deploy'), _WORKSPACE,
              effect='deploy', kind='deploy', label='Uncertain delivery'),
    ), _WORKSPACE, settings={'hidden': 'settings-dictionary-value'},
        adapter={'hidden': 'adapter-dictionary-value'})


def failed_case(number=0, message='AssertionError: expected three items'):
    return dict(suite='fixture.suite', classname='FixtureCase', name=f'test_fixture_{number:02}',
                status='failed', message=message)


def fixture_facts():
    return {
        'unit': dict(id='unit', status='failed', kind='test', effect='test', exit_code=1,
                     error='JUnit report contains failing tests.', tests=[failed_case()]),
        'build': dict(id='build', status='skipped', reason='dependency did not pass'),
        'blocked-delivery': dict(id='blocked-delivery', status='skipped', effect='deploy',
                                 reason='dependency did not pass'),
        'completed-delivery': dict(id='completed-delivery', status='passed', effect='deploy'),
        'uncertain-delivery': dict(id='uncertain-delivery', status='unknown', effect='deploy'),
    }


class DiagnosisTests(unittest.TestCase):
    def test_blocked_delivery_names_its_prerequisite_and_run_names_the_assertion(self):
        plan, facts = fixture_plan(), fixture_facts()
        facts.pop('uncertain-delivery')
        before = deepcopy(facts)
        blocked = diagnose(plan, facts, outcome='failed', selected='blocked-delivery')
        diagnosis = diagnose(plan, facts, outcome='failed', log_text='ERROR: generic fixture log failure\n')

        self.assertEqual(blocked.step_id, 'blocked-delivery')
        self.assertEqual(blocked.blockers, ('build',))
        self.assertEqual(diagnosis.step_id, 'unit')
        self.assertEqual(diagnosis.test_id, 'FixtureCase.test_fixture_00')
        self.assertIn('expected three items', diagnosis.message)
        self.assertEqual(facts, before)

    def test_specific_recorded_error_precedes_a_diagnostic_log_hint(self):
        plan = fixture_plan()
        facts = {'unit': dict(status='failed', error='The recorded compiler check timed out.', exit_code=2)}
        diagnosis = diagnose(plan, facts, outcome='failed', log_text='ERROR: synthetic stale log line\n')
        self.assertIn('recorded compiler check', diagnosis.message)
        self.assertFalse(diagnosis.hint)

    def test_preflight_uses_the_actionable_line_before_the_retained_summary(self):
        plan = fixture_plan()
        facts = {'unit': dict(id='unit', kind='preflight', status='failed', exit_code=2,
                              summary='Checked metadata.\nPreflight complete.')}
        diagnosis = diagnose(plan, facts, outcome='failed', log_text=(
            'Checking fixture tools\nERROR: Fixture compiler was not found\nChecked metadata\n'))
        self.assertEqual(diagnosis.step_id, 'unit')
        self.assertIn('Fixture compiler was not found', diagnosis.message)
        self.assertTrue(diagnosis.hint)

    def test_generic_nonzero_exit_does_not_claim_missing_tools_or_a_crash(self):
        plan = fixture_plan()
        generic = diagnose(plan, {'unit': {'id': 'unit', 'status': 'failed', 'exit_code': 2}},
                           outcome='failed')
        crashed = diagnose(plan, {'unit': {'id': 'unit', 'status': 'failed', 'exit_code': -11}},
                           outcome='failed')

        self.assertNotIn('missing', generic.title.lower())
        self.assertNotIn('crash', generic.title.lower())
        self.assertIn('crash', crashed.title.lower())
        self.assertNotEqual(crashed.category, generic.category)

    def test_controller_failure_is_distinct_from_the_workload_crash(self):
        plan = fixture_plan()
        child = diagnose(plan, {'unit': {'id': 'unit', 'status': 'failed', 'exit_code': -11}},
                         outcome='failed')
        controller = diagnose(plan, {}, outcome='unverified', run_error='Execution process crashed.')

        self.assertNotEqual(controller.category, child.category)
        self.assertFalse(controller.step_id)
        self.assertIn('Execution process crashed', controller.message)

    def test_unknown_delivery_remains_prominent_alongside_the_failed_test(self):
        plan, facts = fixture_plan(), fixture_facts()
        diagnosis = diagnose(plan, facts, outcome='unknown')
        self.assertEqual(diagnosis.step_id, 'uncertain-delivery')
        self.assertIn('unknown', diagnosis.title.lower())

        report = {'status': 'unknown', 'phases': list(facts.values())}
        before = deepcopy(report)
        copied = format_diagnostics(plan, report)
        self.assertIn('unknown', copied.lower())
        self.assertIn('1 completed', copied.lower())
        self.assertIn('1 blocked', copied.lower())
        self.assertIn('1 unknown', copied.lower())
        self.assertEqual(report, before)


class ShareTextTests(unittest.TestCase):
    @patch.dict(os.environ, {'FIXTURE_TOKEN': 'fixture-environment-secret'}, clear=True)
    def test_share_filter_handles_independent_private_forms(self):
        redactor = ShareRedactor(secrets=('fixture-explicit-secret',))
        cases = (
            ('fixture-explicit-secret', 'Observed fixture-explicit-secret'),
            ('fixture-environment-secret', 'Observed fixture-environment-secret'),
            ('ghp_' + 'x' * 32, 'Observed ghp_' + 'x' * 32),
            ('fixture-bearer-value', 'Authorization: Bearer fixture-bearer-value'),
            ('fixture-basic-value', 'Authorization: Basic fixture-basic-value'),
            ('fixture-quoted-value', 'Warning password="starts with fixture-quoted-value"'),
            ('fixture-option-value', 'Warning --token fixture-option-value'),
            ('fixture-private-account', 'https://fixture-private-account:password@example.test/task'),
            ('example.test', 'Fetch https://example.test/path?diagnostic=fixture-private-query'),
            ('fixture-posix', 'File "/Users/fixture-posix/Personal Folder/source.py", line 8'),
            ('fixture-posix-tail', 'Open /Users/Fixture fixture-posix-tail/Private Source.py'),
            ('fixture-windows', r'Open C:\Users\fixture-windows\Private\source.py'),
            ('fixture-windows-tail', r'Open C:\Users\Fixture fixture-windows-tail\Private Source.py'),
            ('fixture-unc', r'Open \\fixture-unc\private\source.py'),
            ('fixture-file-url', 'Open file:///Users/fixture-file-url/source.py'),
            ('fixture-env-assignment', 'LOCAL_DEVICE_LABEL=fixture-env-assignment'),
            ('fixture-reference', 'credential_reference=fixture-reference'),
            ('fixture-private-reference', 'Check protected_file: fixture-private-reference'),
            ('fixture-private-device', 'Check device_id: fixture-private-device'),
            ('fixture-private-account-name', 'ERROR: account name: fixture-private-account-name'),
            ('fixture-command-argument', 'Command: tool --selector fixture-command-argument'),
            ('fixture-osc-target', '\x1b]8;;https://fixture-osc-target.test\x07link\x1b]8;;\x07'),
            ('fixture-osc-title', 'Failure note\x1b]0;fixture-osc-title\x07 still readable'),
        )
        for private_value, field in cases:
            with self.subTest(private_value=private_value):
                text = redactor.text(field)
                self.assertNotIn(private_value, text)
                self.assertNotIn('\x1b', text)
                self.assertNotIn('\x07', text)

    @patch.dict(os.environ, {}, clear=True)
    def test_key_block_state_stays_within_each_field(self):
        redactor = ShareRedactor()
        text = redactor.text('First observable line\n-----BEGIN PRIVATE KEY-----\n'
                             'fixture-private-key-content\n-----END PRIVATE KEY-----\nLast observable line')
        self.assertIn('First observable line', text)
        self.assertIn('Last observable line', text)
        self.assertNotIn('fixture-private-key-content', text)
        self.assertNotIn('PRIVATE KEY-----', text)

        incomplete = redactor.text('-----BEGIN OPENSSH PRIVATE KEY-----\nfixture-incomplete-key-content')
        self.assertNotIn('fixture-incomplete-key-content', incomplete)
        self.assertEqual(redactor.text('Independent failure is still readable'),
                         'Independent failure is still readable')

    @patch.dict(os.environ, {}, clear=True)
    def test_saved_share_uses_allowlisted_context_and_historical_engine(self):
        plan, facts = fixture_plan(), fixture_facts()
        report = dict(status='failed', phases=list(facts.values()), engine={
            'api': 1, 'manager': {'commit': 'a' * 40, 'fingerprint': 'engine-private-fingerprint'},
            'commonUtils': {'commit': 'b' * 40},
        }, raw_report_value='report-dictionary-value')
        text = format_diagnostics(plan, report, selected='unit', context={
            'origin': 'Saved run', 'run_id': 'fixture-run-id', 'python_version': '3.12.2', 'qt_version': '6.8.0',
            'source': {'hidden': 'context-dictionary-value'},
        })

        for public_value in ('Diagnostic fixture', 'Unit tests', 'expected three items', 'fixture.suite',
                             'test_fixture_00', 'Not recorded', 'fixture-run-id', '3.12.2', '6.8.0'):
            with self.subTest(public_value=public_value):
                self.assertIn(public_value, text)
        self.assertIn('aaaaaaa', text)
        self.assertIn('bbbbbbb', text)
        self.assertIn('Viewer Python', text)
        self.assertIn('Viewer Qt', text)
        for private_value in (_WORKSPACE, 'argv-private-value', 'environment-dictionary-value',
                              'source-dictionary-value', 'settings-dictionary-value', 'adapter-dictionary-value',
                              'report-dictionary-value', 'context-dictionary-value', 'engine-private-fingerprint'):
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value, text)

    @patch.dict(os.environ, {}, clear=True)
    def test_share_caps_case_count_and_utf8_bytes(self):
        plan, facts = fixture_plan(), fixture_facts()
        facts['unit']['tests'] = [failed_case(n, 'AssertionError: ' + '重' * 9000) for n in range(40)]
        report = {'status': 'failed', 'phases': list(facts.values())}
        text = format_diagnostics(plan, report, selected='unit',
                                  context={'origin': 'current', 'preset': '行' * 9000})

        self.assertLessEqual(len(text.encode('utf-8')), _COPY_LIMIT)
        self.assertRegex(text.lower(), 'omit|truncat')
        self.assertIn('test_fixture_19', text)
        self.assertNotIn('test_fixture_20', text)

    @patch.dict(os.environ, {}, clear=True)
    def test_log_excerpt_preserves_key_state_before_selecting_diagnostic_lines(self):
        plan, facts = fixture_plan(), fixture_facts()
        facts['unit'].pop('tests')
        facts['unit']['error'] = 'Fixture compiler validation failed.'
        log = ('Starting fixture tools\n-----BEGIN PRIVATE KEY-----\n'
               + 'ERROR: fixture-private-prefix-contents\n' * 100
               + '-----END PRIVATE KEY-----\nERROR: Public compiler detail\n')
        text = format_diagnostics(plan, facts=facts, selected='unit', log_text=log)

        self.assertIn('Public compiler detail', text)
        self.assertNotIn('fixture-private-prefix-contents', text)

    @patch.dict(os.environ, {}, clear=True)
    def test_excerpt_caps_complete_lines(self):
        log = 'ERROR: Public compiler detail\n' + ''.join(f'Fixture line {i:03}\n' for i in range(150))
        text = format_diagnostics(fixture_plan(), facts={'unit': {'status': 'failed'}}, selected='unit',
                                  log_text=log)

        excerpt = text.split('Excerpt:\n', 1)[1].split('\n\n', 1)[0]
        self.assertLessEqual(len(excerpt.splitlines()), 80)
        self.assertIn('Fixture line 077', text)
        self.assertNotIn('Fixture line 079', text)
        self.assertRegex(text.lower(), 'omit|truncat')

    @patch.dict(os.environ, {}, clear=True)
    def test_excerpt_does_not_copy_an_incomplete_line_at_its_byte_budget(self):
        log = 'ERROR: Public compiler detail\nCut line begins ' + '編' * 9000 + '\n'
        text = format_diagnostics(fixture_plan(), facts={'unit': {'status': 'failed'}}, selected='unit',
                                  log_text=log)

        excerpt = text.split('Excerpt:\n', 1)[1].split('\n\n', 1)[0]
        self.assertLessEqual(len(excerpt.encode('utf-8')), 8192)
        self.assertIn('Public compiler detail', text)
        self.assertNotIn('Cut line begins', text)
        self.assertRegex(text.lower(), 'omit|truncat')

    @patch.dict(os.environ, {}, clear=True)
    def test_headline_derivation_never_reintroduces_redacted_traceback_source(self):
        case = failed_case(message='Traceback (most recent call last):\n'
                           '    fixture_call("FixtureError: fixture-private-source-value")\n'
                           'Fixture test failed')
        text = format_diagnostics(fixture_plan(), facts={'unit': {'status': 'failed', 'tests': [case]}},
                                  selected='unit', include_excerpt=False)

        self.assertNotIn('fixture-private-source-value', text)

    @patch.dict(os.environ, {}, clear=True)
    def test_excerpt_can_be_omitted_without_losing_retained_failure_context(self):
        plan, facts = fixture_plan(), fixture_facts()
        facts['unit'].pop('tests')
        facts['unit']['error'] = 'Fixture compiler validation failed.'
        log = 'ERROR: Fixture compiler validation failed.\nUnique excerpt context line\n'
        report = {'status': 'failed', 'phases': list(facts.values())}
        with_excerpt = format_diagnostics(plan, report, selected='unit', log_text=log)
        without_excerpt = format_diagnostics(plan, report, selected='unit', log_text=log, include_excerpt=False)
        self.assertIn('Unique excerpt context line', with_excerpt)
        self.assertNotIn('Unique excerpt context line', without_excerpt)
        self.assertIn('Fixture compiler validation failed.', without_excerpt)

    @patch.dict(os.environ, {}, clear=True)
    def test_selected_failed_case_controls_headline_and_excerpt_without_changing_identities(self):
        first = failed_case(0, 'AssertionError: First fixture failure\nFirst fixture excerpt')
        second = failed_case(1, 'AssertionError: Second fixture failure\nSecond fixture excerpt')
        facts = {'unit': {'status': 'failed', 'tests': [first, second]}}
        before = deepcopy(facts)
        text = format_diagnostics(fixture_plan(), facts=facts, selected='unit', test_id='FixtureCase.test_fixture_01')

        self.assertIn('AssertionError: Second fixture failure', text)
        self.assertIn('Second fixture excerpt', text)
        self.assertNotIn('First fixture failure', text)
        self.assertNotIn('First fixture excerpt', text)
        self.assertIn('FixtureCase.test_fixture_00', text)
        self.assertIn('FixtureCase.test_fixture_01', text)
        self.assertEqual(facts, before)


class RetainedLogTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = self.directory / 'run'
        self.root.mkdir()

    def test_empty_missing_available_and_oversized_are_distinct(self):
        path = self.root / 'step.log'
        self.assertEqual(read_log(self.root, path.name).status, 'missing')
        path.touch()
        self.assertEqual(read_log(self.root, path.name).status, 'empty')
        path.write_bytes(b'Complete output without newline')
        available = read_log(self.root, path.name)
        self.assertEqual(available.status, 'available')
        self.assertEqual(available.text, 'Complete output without newline')
        self.assertFalse(available.truncated)

        first = b'Complete first line\n'
        boundary = b'P' * (_LOG_LIMIT - len(first) - 1) + b'\n'
        original = first + boundary + b'Secret beyond inspected prefix\n'
        path.write_bytes(original)
        bounded = read_log(self.root, path.name)
        self.assertEqual(bounded.status, 'truncated')
        self.assertTrue(bounded.truncated)
        self.assertEqual(bounded.text.encode(), first + boundary)
        self.assertEqual(path.read_bytes(), original)

        path.write_bytes(first + boundary)
        exact = read_log(self.root, path.name)
        self.assertEqual(exact.status, 'available')
        self.assertFalse(exact.truncated)

    def test_partial_line_at_the_byte_limit_is_discarded(self):
        path = self.root / 'step.log'
        prefix = b'First complete line\nSecond complete line\n'
        original = prefix + ('片' * _LOG_LIMIT).encode('utf-8') + b'\nLast line\n'
        path.write_bytes(original)
        bounded = read_log(self.root, path.name)

        self.assertEqual(bounded.status, 'truncated')
        self.assertEqual(bounded.text.encode(), prefix)
        self.assertEqual(path.read_bytes(), original)

    def test_oversized_directory_is_rejected_as_a_log(self):
        path = self.root / 'directory.log'
        path.mkdir()
        (path / 'oversized-content').write_bytes(b'x' * (_LOG_LIMIT + 1))
        with self.assertRaises(ValueError):
            read_log(self.root, path.name)

    def test_unsafe_relative_and_absolute_references_are_rejected(self):
        outside = self.directory / 'outside.log'
        outside.write_text('Outside record', encoding='utf-8')
        for reference in ('../outside.log', str(outside), r'C:\outside.log', r'\\server\outside.log'):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                read_log(self.root, reference)
        self.assertEqual(outside.read_text(encoding='utf-8'), 'Outside record')

    def test_symlink_log_parent_and_root_are_rejected(self):
        outside = self.directory / 'outside'
        outside.mkdir()
        target = outside / 'outside.log'
        target.write_text('Outside record', encoding='utf-8')
        try:
            (self.root / 'linked.log').symlink_to(target)
            (self.root / 'linked').symlink_to(outside, target_is_directory=True)
            linked_root = self.directory / 'linked-root'
            linked_root.symlink_to(self.root, target_is_directory=True)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f'Symlinks unavailable: {error}')
        (self.root / 'step.log').write_text('Retained record', encoding='utf-8')

        for root, reference in ((self.root, 'linked.log'), (self.root, 'linked/outside.log'),
                                (linked_root, 'step.log')):
            with self.subTest(root=root, reference=reference), self.assertRaises(ValueError):
                read_log(root, reference)
        self.assertEqual(target.read_text(encoding='utf-8'), 'Outside record')

    def test_unreadable_regular_file_is_not_missing(self):
        path = self.root / 'protected.log'
        path.write_text('Protected retained output', encoding='utf-8')
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest('This test account can read mode-zero files')
        unreadable = read_log(self.root, path.name)
        self.assertEqual(unreadable.status, 'unreadable')
        self.assertEqual(unreadable.text, '')
