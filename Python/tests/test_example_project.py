"""Keep the project-onboarding example executable and its evidence truthful."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import venv

from build_manager import Executor, Plan
from build_manager.registry import inspect
from build_manager.test_results import read_junit

EXAMPLE = Path(__file__).resolve().parent / 'fixtures/testing_project'


class ExampleProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'project'
        shutil.copytree(EXAMPLE, self.root,
                        ignore=shutil.ignore_patterns('.venv', 'test-results', '__pycache__'))

    def request(self, **overrides):
        values = dict(operation='Test', target='host', backend='Local', suite='labels')
        values.update(overrides)
        return subprocess.run([sys.executable, str(self.root / 'bridge.py')],
            cwd=self.root, input=json.dumps(dict(schema=1, action='plan', values=values)),
            capture_output=True, text=True, timeout=30)

    def plan(self):
        result = self.request()
        self.assertEqual(result.returncode, 0, result.stderr)
        return Plan.from_data(json.loads(result.stdout)['result'])

    def test_descriptor_plan_file_preview_and_frozen_source_produce_real_cases(self):
        descriptor, _ = inspect(self.root)
        self.assertEqual(descriptor['test_suites'][0]['id'], 'labels')
        full = self.request(suite='')
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertEqual([row['id'] for row in json.loads(full.stdout)['result']['phases']], ['labels'])
        plan = self.plan()
        check = plan.phases[0]
        self.assertEqual(check.test_files, ('test_labels.py',))
        self.assertEqual(check.artifact_types[check.artifacts[0]], 'junit')
        (self.root / 'labels.py').write_text("raise RuntimeError('later working-tree edit')\n")
        output = self.root / 'test-results' / 'run'
        result = Executor().run(plan, output)
        self.assertEqual(result['status'], 'passed', result)
        cases = read_junit(check.artifacts[0])
        self.assertEqual(len(cases), 2)
        self.assertEqual({case['status'] for case in cases}, {'passed'})
        self.assertTrue(all(case['seconds'] is not None for case in cases))

    def test_assertion_failure_is_retained_as_failed_junit(self):
        source = self.root / 'tests/test_labels.py'
        source.write_text(source.read_text().replace("'Untitled'", "'Wrong'"))
        plan = self.plan()
        result = Executor().run(plan, self.root / 'test-results' / 'failed-run')
        self.assertEqual(result['status'], 'failed')
        cases = read_junit(plan.phases[0].artifacts[0])
        self.assertEqual(len(cases), 2)
        self.assertEqual({case['status'] for case in cases}, {'passed', 'failed'})
        self.assertTrue(any('Wrong' in case['message'] for case in cases))

    def test_unknown_suite_and_unsupported_narrowing_fail_before_source_capture(self):
        for values in ({'suite': 'missing'}, {'pattern': 'test_other*'}, {'revision': 'HEAD'}):
            with self.subTest(values=values):
                result = self.request(**values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertFalse((self.root / 'test-results').exists())


    def test_cli_registration_uses_the_isolated_project_interpreter(self):
        venv.EnvBuilder(with_pip=False).create(self.root / '.venv')
        interpreter = self.root.resolve() / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        site = subprocess.check_output([str(interpreter), '-c',
            'import site; print(site.getsitepackages()[0])'], text=True, timeout=30).strip()
        # Explicit offline source binding, equivalent to an editable install for
        # this fixture only. No inherited site packages or PYTHONPATH are needed.
        manager_source = Path(__file__).resolve().parents[1]
        (Path(site) / 'reviewed-manager.pth').write_text(str(manager_source) + '\n')
        registry = self.root.parent / 'registry'
        def cli(*arguments):
            result = subprocess.run([sys.executable, '-m', 'build_manager.cli',
                '--registry', str(registry), *arguments], capture_output=True,
                text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        registration = cli('add', str(self.root))['registration']
        project = 'org.example.manager-testing-walkthrough'
        capabilities = cli('capabilities', '--project', project)
        self.assertEqual(capabilities['descriptor']['test_suites'][0]['id'], 'labels')
        path = self.root.parent / 'plan.json'
        cli('plan', '--project', project, '--operation', 'Test', '--target', 'host',
            '--backend', 'Local', '--suite', 'labels', '--output', str(path))
        plan = Plan.load(path)
        self.assertEqual(Path(plan.phases[0].argv[0]), interpreter)
        cli('show-plan', str(path))
        output = self.root.parent / 'run'
        cli('run', str(path), '--output', str(output))
        cli('status', str(output))
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['status'], 'passed')
        cases = read_junit(plan.phases[0].artifacts[0])
        self.assertEqual(len(cases), 2)
        self.assertEqual({case['status'] for case in cases}, {'passed'})
        cli('remove', registration)
        self.assertEqual(cli('list')['projects'], {})
