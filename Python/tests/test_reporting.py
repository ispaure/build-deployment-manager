"""Actual stdlib case production, failure semantics and unknown durations."""
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import subprocess
import sys
from unittest.mock import patch

from build_manager.reporting import run_suite, write_junit
from build_manager.test_results import read_junit


class ReportingTests(unittest.TestCase):
    def test_real_cases_keep_failures_subtests_expected_failures_and_measurements(self):
        class Fixture(unittest.TestCase):
            def test_pass(self):
                pass
            def test_subtest(self):
                with self.subTest(value=1):
                    self.fail('subtest evidence')
            @unittest.expectedFailure
            def test_expected(self):
                self.fail('known issue')
        with TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            output = Path(directory) / 'cases.xml'
            result = run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Fixture), output, 'fixture', fail_on_skip=True)
            self.assertEqual(result['status'], 'failed')
            cases = read_junit(output)
            self.assertEqual({case['status'] for case in cases}, {'passed','failed','skipped'})
            self.assertTrue(all(case['seconds'] >= 0 for case in cases))
            self.assertIn('subtest evidence', '\n'.join(case['message'] for case in cases))

    def test_expected_failure_alone_cannot_satisfy_a_strict_gate(self):
        class Fixture(unittest.TestCase):
            @unittest.expectedFailure
            def test_expected(self):
                self.fail('known')
        with TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            result = run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Fixture), Path(directory)/'cases.xml', 'fixture', fail_on_skip=True)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['skipped'], 1)

    def test_empty_and_fixture_errors_cannot_become_success(self):
        class Fixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError('class fixture failed')
            def test_never(self):
                self.fail('must not run')
        with TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            output = Path(directory)/'cases.xml'
            for suite in (unittest.TestSuite(), unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)):
                result = run_suite(suite, output, 'fixture')
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(read_junit(output)[0]['status'], 'error')

    def test_xml_control_bytes_secret_filtering_and_unknown_duration(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'GH_TOKEN':'synthetic-secret'}):
            output = Path(directory)/'cases.xml'
            write_junit(output,'fixture',[dict(name='native\x00case',status='failed',seconds=None,message='synthetic-secret\x01failed')])
            cases = read_junit(output)
            self.assertEqual(cases[0]['name'], 'nativecase')
            self.assertIsNone(cases[0]['seconds'])
            self.assertNotIn('synthetic-secret', output.read_text())

    def test_producer_is_headless(self):
        subprocess.run([sys.executable, '-c', 'import sys;import build_manager.reporting;'
            'assert not any(name.startswith(("PySide6","bpy","mobile")) for name in sys.modules)'], check=True)
