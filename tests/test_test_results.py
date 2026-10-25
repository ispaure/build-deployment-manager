"""Project suite and case evidence contracts with real harmless subprocesses."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Executor, Phase, Plan
from build_manager.test_results import read_junit, validate_suites


class JUnitTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'report.xml'

    def parse(self, xml):
        self.path.write_text(xml, encoding='utf-8')
        return read_junit(self.path)

    def test_nested_namespaced_reports_preserve_outcomes_identity_time_and_messages(self):
        cases = self.parse('''<testsuites xmlns="urn:junit"><testsuite name="outer"><testsuite name="café">
          <testcase name="pass" classname="contracts.One" time=".125"/>
          <testcase name="fail"><failure message="expected">trace</failure></testcase>
          <testcase name="error"><error message="runtime"/></testcase>
          <testcase name="skip"><skipped message="host unavailable"/></testcase>
        </testsuite></testsuite></testsuites>''')
        self.assertEqual([case['status'] for case in cases], ['passed', 'failed', 'error', 'skipped'])
        self.assertEqual(cases[0]['suite'], 'café')
        self.assertEqual(cases[0]['seconds'], .125)
        self.assertEqual(cases[1]['message'], 'expected\ntrace')

    def test_invalid_reports_are_actionable(self):
        for xml in ('broken', '<html/>', '<testsuite/>', '<testsuite><testcase/></testsuite>',
                    '<testsuite><testcase name="a" time="nan"/></testsuite>',
                    '<testsuite><testcase name="a" time="-1"/></testsuite>',
                    '<testsuite><testcase name="a" time="oops"/></testsuite>',
                    '<!DOCTYPE testsuite [<!ENTITY x "expanded">]><testsuite/>'):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.parse(xml)

    def test_parser_limits_and_non_utf8_reports(self):
        with patch('build_manager.test_results.MAX_REPORT_BYTES', 10), self.assertRaisesRegex(ValueError, 'limit'):
            self.parse('<testsuite><testcase name="a"/></testsuite>')
        with patch('build_manager.test_results.MAX_CASES', 1), self.assertRaisesRegex(ValueError, 'case limit'):
            self.parse('<testsuite><testcase name="a"/><testcase name="b"/></testsuite>')
        self.path.write_bytes('<testsuite/>'.encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            read_junit(self.path)

    def execute_report(self, xml, exit_code=0, *, dependent=False):
        code = f'import os; from pathlib import Path; Path({str(self.path)!r}).write_text({xml!r}.replace("ENV_SECRET", os.environ.get("GH_TOKEN", ""))); raise SystemExit({exit_code})'
        phases = [Phase('contracts', (sys.executable, '-c', code), str(self.root),
                        artifacts=(str(self.path),), artifact_types={str(self.path): 'junit'})]
        if dependent:
            phases.append(Phase('delivery', (sys.executable, '-c', 'raise AssertionError("never")'),
                                str(self.root), dependencies=('contracts',), effect='upload'))
        plan = Plan('Fixture', 'Test', {}, tuple(phases), str(self.root / 'workspace'))
        self.events = []
        return Executor(event=self.events.append).run(plan, self.root / 'result')

    def test_zero_exit_cannot_override_failing_junit_and_delivery_is_blocked(self):
        report = self.execute_report('<testsuite><testcase name="a"><failure message="wrong"/></testcase></testsuite>', dependent=True)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([row['status'] for row in report['phases']], ['failed', 'skipped'])
        self.assertEqual(report['phases'][0]['tests'][0]['status'], 'failed')

    def test_nonzero_exit_retains_case_report_and_never_turns_green(self):
        report = self.execute_report('<testsuite><testcase name="a" time="1.5"/></testsuite>', 3)
        row = report['phases'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['tests'][0]['seconds'], 1.5)
        self.assertTrue(Path(row['artifacts'][0]['path']).is_file())

    def test_malformed_declared_report_fails_phase_with_message(self):
        report = self.execute_report('<oops>')
        self.assertEqual(report['status'], 'failed')
        self.assertIn('JUnit XML', report['phases'][0]['error'])

    def test_case_values_are_redacted_in_result_and_events(self):
        with patch.dict('os.environ', {'GH_TOKEN': 'synthetic-case-secret'}):
            report = self.execute_report('<testsuite><testcase name="a"><failure message="ENV_SECRET"/></testcase></testsuite>')
        self.assertNotIn('synthetic-case-secret', json.dumps(report))
        self.assertNotIn('synthetic-case-secret', json.dumps(self.events))
        self.assertIn('[redacted]', report['phases'][0]['tests'][0]['message'])

    def test_headless_modules_do_not_import_qt_or_project_modules(self):
        code = ('import sys; import build_manager.test_results, build_manager.history; '
                'assert not any(n.startswith(("PySide6", "mobile", "bpy")) for n in sys.modules)')
        subprocess.run([sys.executable, '-c', code], check=True)


class SuiteContractTests(unittest.TestCase):
    capabilities = {'platforms': ['desktop'], 'operations': ['Test']}

    def suite(self, **changes):
        return dict(dict(id='portable.contracts', label='Contracts', tier='contracts',
                         platforms=['desktop'], operations=['Test']), **changes)

    def test_legacy_and_valid_catalog(self):
        self.assertEqual(validate_suites([], self.capabilities), [])
        self.assertEqual(validate_suites([self.suite()], self.capabilities)[0]['id'], 'portable.contracts')

    def test_duplicate_invalid_or_inapplicable_suites(self):
        invalid = [None, {}, [None], [self.suite(), self.suite()]]
        for field, value in [('id', '../escape'), ('tier', 'magic'), ('label', ''),
                             ('platforms', ['other']), ('operations', []), ('description', 3)]:
            suite = self.suite()
            suite[field] = value
            invalid.append([suite])
        for suites in invalid:
            with self.subTest(suites=suites), self.assertRaises(ValueError):
                validate_suites(suites, self.capabilities)
