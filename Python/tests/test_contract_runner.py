"""All modules remain mandatory and native child aborts remain failures."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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

    def test_windows_offscreen_children_use_existing_system_fonts_without_changing_parent(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            fonts = root / 'Fonts'; fonts.mkdir()
            tests = root / 'tests'; tests.mkdir()
            (tests / 'test_fixture.py').write_text('')
            for root_key in ('SYSTEMROOT', 'SystemRoot', 'WINDIR'):
                for platform in (None, 'offscreen', 'offscreen:configfile=fixture.json'):
                    with self.subTest(root_key=root_key, platform=platform):
                        environment = {root_key: str(root)}
                        if platform is not None:
                            environment['QT_QPA_PLATFORM'] = platform
                        calls = []
                        def execute(argv, *, env):
                            calls.append(env)
                            return SimpleNamespace(returncode=0)
                        with patch('build_manager.contracts.os', SimpleNamespace(
                                name='nt', environ=environment, pathsep=os.pathsep)):
                            self.assertEqual(run_modules(tests, runner=execute), [])
                        self.assertEqual(calls[0]['QT_QPA_FONTDIR'], str(fonts))
                        self.assertNotIn('QT_QPA_FONTDIR', environment)

    def test_font_defaults_preserve_explicit_choices_and_other_hosts(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Fonts').mkdir()
            tests = root / 'tests'; tests.mkdir()
            (tests / 'test_fixture.py').write_text('')
            cases = [
                ('nt', {'QT_QPA_PLATFORM': 'windows'}),
                ('nt', {'QT_QPA_PLATFORM': ''}),
                ('nt', {'QT_QPA_FONTDIR': '/explicit/fonts'}),
                ('nt', {'QT_QPA_FONTDIR': ''}),
                ('posix', {}),
                ('nt', {'SYSTEMROOT': str(root / 'missing')}),
                ('nt', {'SYSTEMROOT': ''}),
            ]
            for system, overrides in cases:
                with self.subTest(system=system, overrides=overrides):
                    environment = dict(SYSTEMROOT=str(root), **overrides) if 'SYSTEMROOT' not in overrides else overrides
                    calls = []
                    def execute(argv, *, env):
                        calls.append(env)
                        return SimpleNamespace(returncode=0)
                    with patch('build_manager.contracts.os', SimpleNamespace(
                            name=system, environ=environment, pathsep=os.pathsep)):
                        self.assertEqual(run_modules(tests, runner=execute), [])
                    self.assertEqual(calls[0].get('QT_QPA_FONTDIR'), environment.get('QT_QPA_FONTDIR'))


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
