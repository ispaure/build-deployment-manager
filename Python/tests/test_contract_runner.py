"""All modules remain mandatory and native child aborts remain failures."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from build_manager.contracts import run_modules


class ContractRunnerTests(unittest.TestCase):
    def test_module_boundaries_preserve_aborts_and_run_remaining_modules(self):
        with TemporaryDirectory() as folder:
            for name in ('test_c.py', 'test_a.py', 'test_b.py'):
                (Path(folder) / name).write_text('')
            calls = []
            def execute(argv, *, env):
                self.assertEqual(env['PYTHONPATH'].split(os.pathsep)[0], str(Path(folder).resolve().parent))
                calls.append(argv)
                return SimpleNamespace(returncode=-6 if argv[-2] == 'test_b.py' else 0)
            self.assertEqual(run_modules(folder, runner=execute, python='fixture-python'), [('test_b.py', -6)])
            self.assertEqual([argv[-2] for argv in calls], ['test_a.py', 'test_b.py', 'test_c.py'])
            self.assertTrue(all(argv[:4] == ['fixture-python', '-m', 'unittest', 'discover'] for argv in calls))

    def test_missing_inventory_cannot_pass(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'No manager contract'):
                run_modules(folder)


    def test_isolated_child_resolves_the_selected_test_tree_source_root(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'Python'
            tests = source / 'tests'
            tests.mkdir(parents=True)
            (source / 'fixture_dependency.py').write_text('VALUE = 42\n')
            (tests / 'test_first_import.py').write_text(
                'from fixture_dependency import VALUE\n'
                'import unittest\n'
                'class ImportTest(unittest.TestCase):\n'
                '    def test_source(self): self.assertEqual(VALUE, 42)\n')
            self.assertEqual(run_modules(tests), [])
