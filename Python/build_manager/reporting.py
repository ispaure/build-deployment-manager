"""Optional stdlib JUnit production for project-owned runners, without Qt."""
import argparse
import os
from pathlib import Path
import re
import time
import unittest
import xml.etree.ElementTree as ET
from .test_progress import emit_test_progress


def write_junit(path, suite, cases):
    """Cases are measured facts; omitted durations remain unknown, not zero."""
    from .redaction import Redactor
    redact = Redactor(os.environ.get(name) for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'FIREBASE_TOKEN'))
    def clean(value):
        # XML 1.0 cannot contain console control bytes or lone surrogates.
        value = Redactor(redact.secrets)(str(value))
        return re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '', value)
    root = ET.Element('testsuite', name=clean(suite), tests=str(len(cases)))
    root.set('failures', str(sum(case['status'] == 'failed' for case in cases)))
    root.set('errors', str(sum(case['status'] == 'error' for case in cases)))
    root.set('skipped', str(sum(case['status'] == 'skipped' for case in cases)))
    for case in cases:
        node = ET.SubElement(root, 'testcase', name=clean(case['name']), classname=clean(case.get('classname', suite)))
        if case.get('stage') is not None:
            from .test_results import STAGE_LABELS
            if case['stage'] not in STAGE_LABELS:
                raise ValueError('Unsupported test execution stage.')
            properties = ET.SubElement(node, 'properties')
            ET.SubElement(properties, 'property', name='test_stage', value=case['stage'])
        if case.get('seconds') is not None:
            node.set('time', str(case['seconds']))
        outcome = {'failed': 'failure', 'error': 'error', 'skipped': 'skipped'}.get(case['status'])
        if case['status'] not in {'passed', 'failed', 'error', 'skipped'}:
            raise ValueError('Unsupported case outcome.')
        if outcome:
            child = ET.SubElement(node, outcome)
            child.text = clean(case.get('message', ''))[:16000]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    ET.ElementTree(root).write(temporary, encoding='utf-8', xml_declaration=True)
    temporary.replace(path)


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


class JUnitResult(unittest.TextTestResult):
    """One actual testcase row per test, including fixture/subtest failures."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases, self.current = [], None

    def startTest(self, test):
        self.started = time.monotonic()
        identity = test.id()
        classname, _, name = identity.rpartition('.')
        self.current = dict(name=name, classname=classname, status='passed', message='')
        emit_test_progress('test_started', name=name, classname=classname,
                           file=os.environ.get('BUILD_MANAGER_TEST_FILE', ''))
        super().startTest(test)

    def stopTest(self, test):
        self.current['seconds'] = time.monotonic() - self.started
        emit_test_progress('test_finished', file=os.environ.get('BUILD_MANAGER_TEST_FILE', ''), **self.current)
        self.cases.append(self.current)
        self.current = None
        super().stopTest(test)

    def outcome(self, test, status, message):
        row = self.current
        if row is None:
            classname, _, name = test.id().rpartition('.')
            row = dict(name=name, classname=classname, status='passed', seconds=0, message='')
            self.cases.append(row)
        if row['status'] not in {'failed', 'error'}:
            row['status'] = status
        row['message'] += message

    def addError(self, test, err):
        self.outcome(test, 'error', self._exc_info_to_string(err, test))
        super().addError(test, err)

    def addFailure(self, test, err):
        self.outcome(test, 'failed', self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addSkip(self, test, reason):
        self.outcome(test, 'skipped', reason)
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.outcome(test, 'skipped', 'Expected failure: ' + self._exc_info_to_string(err, test))
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcome(test, 'failed', 'Unexpected success: update the declared expectation.')
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.outcome(test, 'failed' if issubclass(err[0], test.failureException) else 'error',
                         str(subtest) + '\n' + self._exc_info_to_string(err, test))
        super().addSubTest(test, subtest, err)


def run_suite(suite, output, name, *, fail_on_skip=False):
    expected = list(test_ids(suite))
    result = unittest.TextTestRunner(verbosity=2, resultclass=JUnitResult).run(suite)
    cases = result.cases
    if not cases:
        cases.append(dict(name='discovery', classname=name, status='error', message='No test cases discovered.'))
    write_junit(output, name, cases)
    return dict(status='passed' if expected and result.wasSuccessful() and not (fail_on_skip and (result.skipped or result.expectedFailures)) else 'failed',
                expected_tests=expected, tests_run=result.testsRun, failures=len(result.failures),
                errors=len(result.errors), skipped=len(result.skipped) + len(result.expectedFailures),
                report=str(Path(output).resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=Path, required=True)
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', required=True)
    parser.add_argument('--fail-on-skip', action='store_true')
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    suite = unittest.defaultTestLoader.discover(str(args.start), pattern=args.pattern)
    return int(run_suite(suite, args.output, args.suite, fail_on_skip=args.fail_on_skip)['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
