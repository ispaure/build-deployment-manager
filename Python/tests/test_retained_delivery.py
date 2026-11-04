"""Optional retained delivery scopes callbacks without executing project policy."""
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from build_manager import Phase, Plan
from build_manager.api import ManagerAPI
from build_manager.bridge import ProjectBridge
from build_manager.cli import main
from owned_cleanup import cleanup_private_interpreter


class RetainedDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(cleanup_private_interpreter, temp)
        self.root = Path(temp.name).resolve()
        self.directory = self.root / 'retained'; self.directory.mkdir()
        self.previous = Plan('Fixture', 'Original', {'commit': 'verified-old-source'}, (
            Phase('ready-gate', (sys.executable, '-c', 'pass'), str(self.root)),
            Phase('other-failed', (sys.executable, '-c', 'raise SystemExit(1)'), str(self.root))),
            str(self.root / 'original-workspace'), adapter=dict(project_id='fixture', checkout=str(self.root)))
        self.report = dict(schema=1, status='failed', plan_identity=self.previous.identity,
            phases=[dict(id='ready-gate', status='passed'), dict(id='other-failed', status='failed', exit_code=7)])
        self.save()
        self.project = object.__new__(ProjectBridge)
        self.project.root = self.root
        self.project.descriptor = dict(name='Fixture', project_id='fixture', adapter_actions=['retained_delivery_plan'])
        self.project.row = {'descriptor': 'descriptor-digest'}
        self.project.journey_capability = dict(destinations={'phones': {'label': 'Saved phones'}})
        self.project.run_fields = [dict(id='recipients', label='Recipients', kind='multiselect', default='[]'),
            dict(id='provision', label='Provisioning', kind='choice', default='existing',
                 options={'existing': 'Existing', 'update': 'Authorize updates'})]
        self.fresh = Plan('Fixture', 'Retained delivery', self.previous.source, (
            Phase('verify-retained', (sys.executable, '-c', 'pass'), str(self.root), effect='inspect'),),
            str(self.root / 'new-workspace'))
        self.project.call = Mock(return_value=self.fresh.data())

    def save(self):
        self.previous.save(self.directory / 'plan.json')
        self.report['plan_identity'] = self.previous.identity
        (self.directory / 'result.json').write_text(json.dumps(self.report))

    def prepare(self, destinations=None, **kwargs):
        return self.project.retained_delivery_plan(self.directory,
            ['phones'] if destinations is None else destinations, **kwargs)

    def test_exact_callback_and_old_source_with_other_failed_leg_leave_original_unchanged(self):
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        plan = self.prepare(run_overrides={'recipients': '["saved-phone"]', 'provision': 'update'})
        self.project.call.assert_called_once_with('retained_delivery_plan', timeout=600,
            run_directory=str(self.directory), destinations=['phones'],
            run_overrides={'recipients': '["saved-phone"]', 'provision': 'update'})
        self.assertEqual(plan.source, {'commit': 'verified-old-source'})
        self.assertEqual(plan.adapter['checkout'], str(self.root))
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.iterdir()}, before)
        self.assertFalse(Path(plan.workspace).exists())

    def test_unsupported_action_and_invalid_destinations_do_not_invoke_project(self):
        self.project.descriptor['adapter_actions'] = []
        with self.assertRaisesRegex(ValueError, 'does not offer'):
            self.prepare()
        self.project.descriptor['adapter_actions'] = ['retained_delivery_plan']
        for destinations in [[], 'phones', ['missing'], ['phones', 'phones']]:
            with self.assertRaisesRegex(ValueError, 'distinct'):
                self.prepare(destinations)
        self.project.call.assert_not_called()

    def test_only_declared_nonsecret_valid_choices_cross_the_bridge(self):
        for values in [[], {'missing': 'x'}, {'provision': 'silent-update'}, {'recipients': 'not JSON'}]:
            with self.assertRaises(ValueError):
                self.prepare(run_overrides=values)
        self.project.call.assert_not_called()

    def test_retired_missing_or_wrong_checkout_source_is_rejected_before_callback(self):
        self.report['retirement'] = dict(at='now', reason='released holds'); self.save()
        with self.assertRaisesRegex(ValueError, 'retired'):
            self.prepare()
        self.report.pop('retirement')
        self.previous = replace(self.previous, adapter=dict(project_id='fixture', checkout='/other/checkout'))
        self.save()
        with self.assertRaisesRegex(ValueError, 'registered project'):
            self.prepare()
        (self.directory / 'result.json').unlink()
        with self.assertRaisesRegex(ValueError, 'rebuild'):
            self.prepare()
        self.project.call.assert_not_called()

    def test_project_failure_is_actionable_and_returned_project_workspace_are_checked(self):
        self.project.call.side_effect = ValueError('Retained archive expired; rebuild the selected platform.')
        with self.assertRaisesRegex(ValueError, 'expired; rebuild'):
            self.prepare()
        self.project.call.side_effect = None
        for plan, message in [(replace(self.fresh, project='Other'), 'different project'),
                              (replace(self.fresh, workspace=self.previous.workspace), 'fresh workspace')]:
            self.project.call.return_value = plan.data()
            with self.assertRaisesRegex(ValueError, message):
                self.prepare()

    def test_api_routes_selected_project_without_executing_plan(self):
        api = ManagerAPI(self.root / 'registry')
        with patch.object(api, '_project', return_value=self.project) as select:
            prepared = api.prepare_retained_delivery(self.directory, ['phones'], project='registered')
        select.assert_called_once_with('registered')
        self.assertEqual(prepared.source, self.previous.source)
        self.assertFalse(Path(prepared.workspace).exists())

    def test_cli_prepares_new_plan_and_never_overwrites_evidence(self):
        output = self.root / 'new-plan.json'
        with patch('build_manager.cli.ManagerAPI') as api:
            api.return_value.prepare_retained_delivery.return_value = self.fresh
            with redirect_stdout(StringIO()):
                code = main(['retained-delivery', str(self.directory), '--project', 'registered',
                    '--destination', 'phones', '--run-value', 'recipients=["new-phone"]', '--output', str(output)])
            self.assertEqual(code, 0)
            api.return_value.prepare_retained_delivery.assert_called_once_with(self.directory, ['phones'],
                project='registered', run_overrides={'recipients': '["new-phone"]'})
            api.return_value.prepare_retained_delivery.reset_mock()
            with redirect_stdout(StringIO()):
                self.assertEqual(main(['retained-delivery', str(self.directory),
                    '--destination', 'phones', '--output', str(output)]), 1)
            api.return_value.prepare_retained_delivery.assert_not_called()
        self.assertEqual(Plan.load(output).identity, self.fresh.identity)
        self.assertFalse(Path(self.fresh.workspace).exists())

    def test_registered_optional_hook_round_trip_uses_own_project_interpreter(self):
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(self.root / '.venv')], check=True)
        interpreter = '.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python'
        descriptor = dict(self.project.descriptor, schema=1, adapter_api=1, interpreter=interpreter,
            bridge='bridge.py', capabilities=dict(platforms=['native'], operations=['Check']),
            journey=dict(schema=1, platforms={'native': dict(operation='Check', backend='Local')},
                destinations={'phones': dict(label='Saved phones', platforms=['native'])}))
        (self.root / 'build-project.json').write_text(json.dumps(descriptor))
        (self.root / 'prepared.json').write_text(json.dumps(self.fresh.data()))
        (self.root / 'bridge.py').write_text('''import json,os,sys
from pathlib import Path
request=json.load(sys.stdin)
assert request['action']=='retained_delivery_plan'
assert os.environ['BUILD_MANAGER_DEPENDENCIES']=='project'
assert 'PYTHONPATH' not in os.environ
Path('observed.json').write_text(json.dumps(dict(values=request['values'], interpreter=sys.executable)))
print(json.dumps(dict(schema=1,result=json.loads(Path('prepared.json').read_text()))))
''')
        api = ManagerAPI(self.root / 'private-registry')
        key = api.registry.add(self.root)
        prepared = api.prepare_retained_delivery(self.directory, ['phones'], project=key)
        observed = json.loads((self.root / 'observed.json').read_text())
        self.assertEqual(observed['values'], dict(run_directory=str(self.directory), destinations=['phones'], run_overrides={}))
        self.assertEqual(Path(observed['interpreter']).absolute(), self.root / interpreter)
        self.assertEqual(prepared.source, self.previous.source)
        self.assertFalse(Path(prepared.workspace).exists())
