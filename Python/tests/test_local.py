"""Local prerequisite inspection uses the explicitly selected interpreter."""
import sys
import unittest

from build_manager.local import inspect_python


class LocalInterpreterTests(unittest.TestCase):
    def test_actual_interpreter_reports_architecture_and_packages(self):
        report = inspect_python(sys.executable, ('PySide6',))
        self.assertTrue(report['architecture'])
        self.assertEqual(report['executable'], sys.executable)
        self.assertTrue(report['packages']['PySide6'])

    def test_missing_interpreter_and_package_fail_without_fallback(self):
        with self.assertRaisesRegex(ValueError, 'Python is missing'):
            inspect_python('/missing/python')
        with self.assertRaisesRegex(ValueError, 'required package'):
            inspect_python(sys.executable, ('nonexistent-manager-contract-package',))
