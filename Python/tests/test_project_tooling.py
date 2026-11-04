"""Bootstrap works without a project manager package and never guesses an installer."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from build_manager.api import ManagerAPI
from build_manager.bridge import ProjectBridge
from build_manager.cli import main
from build_manager.project_tooling import validate_status


def status(ready=False, blocked=False):
    return dict(ready=ready, status='ready' if ready else 'blocked' if blocked else 'needs_update',
        message='Ready' if ready else 'Use the declared project repair route.', declared_revision='a' * 40,
        environments=[dict(name=name, interpreter='/project/' + name + '/python', ready=ready,
                           installed_revision='a' * 40 if ready else '', source_checkout='/project/immutable' if ready else '')
                      for name in ('desktop', 'mobile')])


class ProjectToolingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(self.root / '.venv')], check=True)
        python = '.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python'
        descriptor = dict(schema=1, adapter_api=1, project_id='fixture.bootstrap', name='Bootstrap fixture',
            interpreter=python, bridge='bridge.py', capabilities=dict(platforms=['native'], operations=['Check']),
            adapter_actions=['settings', 'tooling_status', 'tooling_update'])
        (self.root / 'build-project.json').write_text(json.dumps(descriptor))
        (self.root / 'response.json').write_text(json.dumps(status()))
        (self.root / 'bridge.py').write_text('''import importlib.util,json,sys
from pathlib import Path
request=json.load(sys.stdin)
assert importlib.util.find_spec('build_manager') is None
action=request['action']
if action in ('tooling_status','tooling_update'):
    assert 'manager_checkout' not in request
    if Path('bootstrap-error').exists():
        raise ValueError('Mock bootstrap error before any SDK import')
    response=json.loads(Path('response.json').read_text())
    if Path('active-lease').exists():
        response.update(status='blocked',ready=False,message='Active project interpreter lease; retry after the run.')
    if action=='tooling_update':
        assert request['values']=={'confirmed':True}
        if Path('active-lease').exists():
            response.update(status='blocked',ready=False,message='Active project interpreter lease; retry after the run.')
        else:
            Path('repair-request.json').write_text(json.dumps(request['values']))
    print(json.dumps(dict(schema=1,result=response)))
else:
    Path('ordinary-import-attempted').touch()
    import unavailable_project_dependency
''')
        self.api = ManagerAPI(self.root / 'registry')
        self.key = self.api.registry.add(self.root)

    def invoke(self, *args):
        stream = StringIO()
        with redirect_stdout(stream):
            code = main(['--registry', str(self.root / 'registry'), *map(str, args)])
        return code, json.loads(stream.getvalue().splitlines()[-1])

    def test_readiness_and_check_project_work_before_unavailable_adapter_import(self):
        result = self.api.tooling_status(self.key)
        self.assertFalse(result['ready'])
        self.assertEqual([row['name'] for row in result['environments']], ['desktop', 'mobile'])
        from build_manager.onboarding import probe_adapter
        check = probe_adapter(self.api.registry, self.key)
        self.assertEqual(check['stage'], 'project_tooling')
        self.assertEqual(check['status'], 'failed')
        self.assertFalse(check['workloads_executed'])
        self.assertIn(['build-manager', 'tooling', '--project', self.key, '--update', '--confirm'],
                      [row['argv'] for row in check['next_actions']])
        self.assertFalse((self.root / 'ordinary-import-attempted').exists())
        self.assertFalse((self.root / 'repair-request.json').exists())

    def test_bootstrap_error_never_falls_back_to_missing_sdk_or_normal_adapter(self):
        (self.root / 'bootstrap-error').touch()
        with self.assertRaisesRegex(ValueError, 'Mock bootstrap error before any SDK import'):
            self.api.tooling_status(self.key)
        self.assertFalse((self.root / 'ordinary-import-attempted').exists())
        self.assertFalse((self.root / 'repair-request.json').exists())

    def test_cli_readonly_and_explicit_repair_route_return_actual_readiness(self):
        code, result = self.invoke('tooling', '--project', self.key)
        self.assertEqual(code, 1); self.assertEqual(result['status'], 'needs_update')
        code, result = self.invoke('tooling', '--project', self.key, '--update')
        self.assertEqual(code, 2)
        self.assertFalse((self.root / 'repair-request.json').exists())
        code, result = self.invoke('tooling', '--project', self.key, '--update', '--confirm')
        self.assertEqual(code, 1)  # This fixture records the request, never invokes an installer.
        self.assertEqual(json.loads((self.root / 'repair-request.json').read_text()), {'confirmed': True})
        self.assertFalse((self.root / 'ordinary-import-attempted').exists())

    def test_active_environment_block_is_preserved_without_mutation(self):
        (self.root / 'active-lease').touch()
        from build_manager.onboarding import probe_adapter
        check = probe_adapter(self.api.registry, self.key)
        self.assertEqual([row['id'] for row in check['next_actions']], ['tooling-status'])
        value = self.api.update_tooling(self.key, confirmed=True)
        self.assertEqual(value['status'], 'blocked')
        self.assertFalse(value['ready'])
        self.assertFalse((self.root / 'repair-request.json').exists())

    def test_confirmation_is_required_before_project_resolution_or_calls(self):
        with patch.object(self.api, '_project') as project:
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                self.api.update_tooling(self.key)
            project.assert_not_called()
        bridge = ProjectBridge(self.api.registry, self.key)
        with patch.object(bridge, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                bridge.update_tooling()
            call.assert_not_called()

    def test_unsupported_optional_actions_never_invoke_adapter(self):
        bridge = ProjectBridge(self.api.registry, self.key)
        bridge.descriptor['adapter_actions'] = []
        with patch.object(bridge, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'setup guide'):
                bridge.tooling_status()
            with self.assertRaisesRegex(ValueError, 'setup guide'):
                bridge.update_tooling(confirmed=True)
            call.assert_not_called()

    def test_ready_cli_result_and_invalid_flag_combination(self):
        with patch('build_manager.cli.ManagerAPI') as api:
            api.return_value.tooling_status.return_value = status(True)
            stream = StringIO()
            with redirect_stdout(stream):
                self.assertEqual(main(['tooling']), 0)
                self.assertEqual(main(['tooling', '--confirm']), 2)
            api.return_value.update_tooling.assert_not_called()


class ToolingShapeTests(unittest.TestCase):
    def test_valid_ready_missing_and_blocked_results_preserve_metadata(self):
        for value in (status(), status(True), status(blocked=True)):
            value['policy_note'] = 'Project owns its immutable installation.'
            self.assertEqual(validate_status(value), value)

    def test_malformed_or_contradictory_environment_status_is_rejected(self):
        invalid = []
        value = status(); value['ready'] = 'yes'; invalid.append(value)
        value = status(); value['status'] = 'ready'; invalid.append(value)
        value = status(True); value['environments'][1]['ready'] = False; invalid.append(value)
        value = status(True); value['environments'] = []; invalid.append(value)
        value = status(); value['environments'][1]['name'] = 'desktop'; invalid.append(value)
        value = status(); value['environments'][0].pop('interpreter'); invalid.append(value)
        for value in invalid:
            with self.assertRaises(ValueError):
                validate_status(deepcopy(value))
