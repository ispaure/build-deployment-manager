"""Real registration/planning/execution without a project bridge or Python environment."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Executor
from build_manager.bridge import ProjectBridge
from build_manager.onboarding import scaffold, check_adapter, readiness
from build_manager.registry import Registry, inspect


class CommandProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project with spaces'
        self.root.mkdir()
        self.registry = Registry(Path(self.temp.name) / 'registry')

    def create(self, code="print('hello')"):
        scaffold(self.root, 'Example', 'org.example.commands', [sys.executable, '-c', code])
        return self.root / 'build-project.json'

    def bridge(self):
        return ProjectBridge(self.registry, self.registry.add(self.root))

    def test_command_project_runs_captured_source_and_retains_artifacts(self):
        path = self.create()
        (self.root / 'input.txt').write_text('before')
        data = json.loads(path.read_text())
        data['commands']['source'] = ['input.txt']
        row = data['commands']['operations']['Check'][0]
        row['argv'] = [sys.executable, '-c', "from pathlib import Path; Path(r'{output}/result.txt').write_text(Path('input.txt').read_text())"]
        row['artifacts'] = ['result.txt']
        path.write_text(json.dumps(data))
        bridge = self.bridge()
        plan = bridge.make_plan('Check', 'host', 'Local')
        (self.root / 'input.txt').write_text('after')
        result = Executor().run(plan, self.root / 'run')
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(Path(plan.phases[0].artifacts[0]).read_text(), 'before')
        self.assertEqual(bridge.settings_view(), {})
        self.assertEqual(check_adapter(self.registry)['stage'], 'adapter_loaded')

    def test_scaffold_never_overwrites_and_cli_does_not_run_command(self):
        marker = self.root / 'executed'
        args = [sys.executable, '-m', 'build_manager.cli', 'init-project', str(self.root),
                '--name', 'CLI example', '--project-id', 'org.example.cli', '--command',
                sys.executable, '-c', f"open({str(marker)!r}, 'w').close()"]
        first = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertFalse(marker.exists())
        original = (self.root / 'build-project.json').read_bytes()
        second = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((self.root / 'build-project.json').read_bytes(), original)

    def test_invalid_commands_and_conflicting_capabilities_rejected(self):
        path = self.create()
        original = json.loads(path.read_text())
        for mutate in [lambda d: d['commands']['operations']['Check'][0].update(argv='echo hello'),
                       lambda d: d['commands']['operations']['Check'][0].update(effect='upload'),
                       lambda d: d.update(capabilities={'platforms': ['other']}),
                       lambda d: d['commands'].update(source=['../private']),
                       lambda d: d['commands']['operations']['Check'][0].update(artifacts=['../escape'])]:
            value = json.loads(json.dumps(original)); mutate(value); path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): inspect(self.root)

    def test_links_missing_source_and_unsupported_selection_fail(self):
        path = self.create()
        data = json.loads(path.read_text())
        data['commands']['source'] = ['missing.py']; path.write_text(json.dumps(data))
        self.assertFalse(readiness(self.root)['ready'])
        bridge = self.bridge()
        with self.assertRaises(ValueError): bridge.make_plan('Check', 'host', 'Local', pattern='narrow')
        with self.assertRaises(ValueError): bridge.make_plan('Check', 'host', 'Local')
        self.assertFalse((self.root / 'test-results').exists())
        try: (self.root / 'missing.py').symlink_to(Path(self.temp.name) / 'outside')
        except OSError: self.skipTest('Host cannot create symlinks')
        self.assertFalse(readiness(self.root)['ready'])

    def test_check_plans_never_execute_and_missing_executable_is_not_ready(self):
        marker = self.root / 'executed'
        path = self.create(f"open({str(marker)!r}, 'w').close()")
        self.bridge()
        result = check_adapter(self.registry, prepare=True)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(result['plans']), 1)
        self.assertFalse(marker.exists())
        data = json.loads(path.read_text()); data['commands']['operations']['Check'][0]['argv'] = ['definitely-no-such-command-bdm']
        path.write_text(json.dumps(data))
        self.assertFalse(readiness(self.root)['ready'])

    def test_gui_and_preset_request_options_are_accepted_without_silent_narrowing(self):
        from build_manager.preparation import WorkflowSelection, preparation_request
        self.create()
        bridge = self.bridge()
        selection = WorkflowSelection(goal='validate', operation='Check', platform='host', backend='Local')
        plan = preparation_request(selection).prepare(bridge)
        self.assertEqual(plan.operation, 'Check')
        with self.assertRaises(ValueError):
            bridge.make_plan('Check', 'host', 'Local', build_override='7')

    def test_malformed_step_shapes_fail_as_validation_errors(self):
        path = self.create()
        original = json.loads(path.read_text())
        for field, value in [('argv', []), ('id', []), ('effect', []), ('timeout', 'forever'),
                             ('dependencies', 'step'), ('environment', []), ('environment', {'x': 7}),
                             ('artifacts', 'result.xml'), ('artifact_types', [])]:
            with self.subTest(field=field, value=value):
                data = json.loads(json.dumps(original))
                data['commands']['operations']['Check'][0][field] = value
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError): inspect(self.root)
