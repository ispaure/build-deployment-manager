"""Integrated intent, isolated bridge, real bounded delivery and credential boundaries."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Executor, Phase, Plan
from build_manager.bridge import ProjectBridge
from build_manager.credentials import protected_reference, reject_secrets
from build_manager.journeys import request, validate_capability, validate_plan, outcomes, for_host
from build_manager.registry import Registry
from build_manager.workflows import approve


CAPABILITIES = dict(platforms=['android', 'ios'], operations=['Test'])
CAPABILITY = dict(schema=1, platforms={
    target: dict(operation='Test', backend='Local', label=target.title()) for target in ('android', 'ios')},
    destinations={name: dict(label=name.title(), platforms=['android' if name == 'firebase' else 'ios'])
                  for name in ('firebase', 'testflight')})


def integrated(root, *, fail_gate=False, fail_delivery=False):
    phases = [Phase(target, (sys.executable, '-c', 'raise SystemExit(1)' if fail_gate and target == 'ios' else 'pass'), str(root))
              for target in ('android', 'ios')]
    artifact = root / 'package.bin'
    phases.append(Phase('prepare', (sys.executable, '-c',
        f'from pathlib import Path;Path({str(artifact)!r}).write_bytes(b"package")'), str(root),
        dependencies=('android', 'ios'), artifacts=(str(artifact),), kind='build', effect='build'))
    for name in ('firebase', 'testflight'):
        target = root / (name + '.json')
        code = (f'import time,json;from pathlib import Path;a=time.time();time.sleep(.2);'
                f'Path({str(target)!r}).write_text(json.dumps([a,time.time()]))')
        if fail_delivery and name == 'firebase':
            code += ';raise SystemExit(1)'
        phases.append(Phase(name, (sys.executable, '-c', code), str(root), dependencies=('prepare',), effect='upload'))
    return Plan('Fixture', 'Validate and deliver', {'commit': 'fixed'}, tuple(phases), str(root / 'workspace'),
        max_workers=2, journey=dict(schema=1, goal='deliver', platforms={'android': ['android'], 'ios': ['ios']},
            destinations={name: dict(identity=name + ':fixture/app/testers', steps=[name]) for name in ('firebase', 'testflight')}))


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_explicit_optional_device_testing_keeps_selected_test_gates(self):
        from copy import deepcopy
        capability = deepcopy(CAPABILITY)
        capability['destinations']['device'] = dict(label='Device', platforms=['android'], testing_optional=True)
        intent = request(capability, 'deliver', [], ['device'], backends={})
        self.assertEqual(intent['destination_platforms']['device'], [])
        prepare = Phase('prepare', (sys.executable, '-c', 'pass'), str(self.root), kind='build', effect='build')
        deploy = Phase('device', (sys.executable, '-c', 'pass'), str(self.root),
                       dependencies=('prepare',), effect='deploy')
        data = dict(schema=1, goal='deliver', platforms={}, executions={}, destinations={
            'device': dict(identity='selected exact device', steps=['device'], platforms=[], testing_optional=True)})
        plan = Plan('Fixture', 'Build and deploy', {}, (prepare, deploy), str(self.root), journey=data)
        validate_plan(plan, intent)
        with self.assertRaises(ValueError):
            request(capability, 'deliver', [], ['firebase'])
        selected = request(capability, 'deliver', ['ios'], ['device'], backends={'ios': 'Local'})
        self.assertEqual(selected['destination_platforms']['device'], ['ios'])
        with self.assertRaises(ValueError):
            validate_plan(plan, selected)

    def test_explicit_host_mappings_do_not_mutate_or_fall_back_to_hosted_execution(self):
        from copy import deepcopy
        capability = deepcopy(CAPABILITY)
        capability['platforms']['android']['backends_by_host'] = {'linux': 'This Linux host'}
        validate_capability(capability, CAPABILITIES)
        self.assertEqual(for_host(capability, 'linux')['platforms']['android']['backend'], 'This Linux host')
        self.assertEqual(for_host(capability, 'darwin')['platforms']['android']['backend'], 'Local')
        self.assertEqual(capability['platforms']['android']['backend'], 'Local')
        capability['platforms']['android']['backends_by_host']['unsupported'] = 'GitHub'
        with self.assertRaisesRegex(ValueError, 'host backends'):
            validate_capability(capability, CAPABILITIES)

    def test_settings_guard_preserves_old_references_but_checks_new_credential_files(self):
        from build_manager.credentials import validate_settings_changes
        rows = {'auth.key_reference': dict(value=str(self.root / 'old.p8'), kind='reference'),
                'tools.desktop_python': dict(value='', kind='reference')}
        validate_settings_changes(rows, {'auth.key_reference': str(self.root / 'old.p8'),
            'tools.desktop_python': str(self.root / 'python')}, self.root)
        with self.assertRaisesRegex(ValueError, 'outside the project checkout'):
            validate_settings_changes(rows, {'auth.key_reference': str(self.root / 'new.p8')}, self.root)

    def test_request_preserves_conflicts_and_validates_before_execution(self):
        validate_capability(CAPABILITY, CAPABILITIES)
        with self.assertRaisesRegex(ValueError, 'requires: android'):
            request(CAPABILITY, 'deliver', ['ios'], ['firebase'])
        with self.assertRaisesRegex(ValueError, 'Validation cannot'):
            request(CAPABILITY, 'validate', ['android'], ['firebase'])
        with self.assertRaisesRegex(ValueError, 'at least one'):
            request(CAPABILITY, 'validate', [], [])
        intent = request(CAPABILITY, 'deliver', ['android', 'ios'], ['firebase', 'testflight'])
        self.assertEqual(intent['platforms'], ['android', 'ios'])
        with self.assertRaises(ValueError):
            validate_capability(dict(CAPABILITY, schema=2), CAPABILITIES)

    def test_returned_plan_cannot_ignore_intent_or_bypass_release_gates(self):
        plan = integrated(self.root)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            validate_plan(plan, request(CAPABILITY, 'validate', ['ios'], []))
        with self.assertRaisesRegex(ValueError, 'required platform'):
            replace(plan, phases=(*plan.phases[:-1], replace(plan.phases[-1], dependencies=('ios',))))
        evidence = dict(plan.journey, destinations={'firebase': plan.journey['destinations']['firebase']})
        with self.assertRaisesRegex(ValueError, 'unselected'):
            replace(plan, journey=evidence)
        with self.assertRaisesRegex(ValueError, 'explicit reviewed'):
            replace(plan, phases=(*(replace(phase, effect='test') for phase in plan.phases[:2]),
                                 *plan.phases[2:-1], replace(plan.phases[-1], effect='inherit')), effect='upload')

    def test_real_run_pauses_and_independent_approved_deliveries_overlap_without_rebuilding(self):
        plan = integrated(self.root)
        executor = Executor(resource_directory=self.root / 'resources')
        first = executor.run(plan, self.root / 'result')
        self.assertEqual(first['status'], 'awaiting_review')
        self.assertFalse((self.root / 'firebase.json').exists())
        approvals = tuple(approve(plan, step, first) for step in ('firebase', 'testflight'))
        last = executor.run(plan, self.root / 'result', resume=True, approvals=approvals)
        self.assertEqual(last['status'], 'passed')
        self.assertEqual(first['phases'][2]['started_at'], last['phases'][2]['started_at'])
        a, b = [json.loads((self.root / (name + '.json')).read_text()) for name in ('firebase', 'testflight')]
        self.assertLess(max(a[0], b[0]), min(a[1], b[1]))
        self.assertTrue(all(state == 'passed' for _, state in outcomes(plan, last['phases'])))

    def test_platform_scoped_delivery_survives_unrelated_failure_and_order_only_wait(self):
        plan = integrated(self.root)
        android, ios = plan.phases[:2]
        android = replace(android, argv=(sys.executable, '-c', 'raise SystemExit(1)'))
        admit = Phase('ios.admit', (sys.executable, '-c', 'pass'), str(self.root), waits_for=('android',), always=True, kind='setup', effect='inspect')
        ios = replace(ios, dependencies=('ios.admit',))
        prepare = replace(plan.phases[2], dependencies=('ios',))
        upload = plan.phases[-1]
        evidence = dict(plan.journey, destinations={'testflight': dict(identity='testflight:fixture',
            steps=['testflight'], platforms=['ios'])})
        plan = replace(plan, phases=(android, admit, ios, prepare, upload), journey=evidence)
        validate_plan(plan, request(CAPABILITY, 'deliver', ['android', 'ios'], ['testflight']))
        executor = Executor(resource_directory=self.root / 'resources')
        first = executor.run(plan, self.root / 'result')
        self.assertEqual(first['status'], 'awaiting_review')
        approval = approve(plan, 'testflight', first)
        final = executor.run(plan, self.root / 'result', resume=True, approvals=(approval,))
        self.assertEqual(final['phases'][-1]['status'], 'passed')
        self.assertEqual(Plan.from_data(plan.data()).phases[1].waits_for, ('android',))
        forged = dict(evidence, destinations={'testflight': dict(identity='testflight:fixture',
            steps=['testflight'], platforms=['android'])})
        with self.assertRaises(ValueError):
            validate_plan(replace(plan, journey=forged), request(CAPABILITY, 'deliver', ['android', 'ios'], ['testflight']))

    def test_required_failure_blocks_every_delivery(self):
        plan = integrated(self.root, fail_gate=True)
        report = Executor(resource_directory=self.root / 'resources').run(plan, self.root / 'result')
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([row['status'] for row in report['phases'][-2:]], ['skipped', 'skipped'])
        self.assertFalse((self.root / 'firebase.json').exists())

    def test_github_devices_and_both_tester_branches_share_reviewed_preparation(self):
        original = integrated(self.root)
        extra = tuple(Phase(name, (sys.executable, '-c', 'pass'), str(self.root),
                            dependencies=('prepare',), effect=effect)
                      for name, effect in (('github', 'publish'), ('devices', 'deploy')))
        evidence = dict(original.journey, destinations=dict(original.journey['destinations'],
            github=dict(identity='owner/repo/v1', steps=['github']),
            devices=dict(identity='authorized-fixture-devices', steps=['devices'])))
        plan = replace(original, phases=(*original.phases, *extra), journey=evidence, max_workers=4)
        executor = Executor(resource_directory=self.root / 'resources')
        first = executor.run(plan, self.root / 'result')
        self.assertEqual([row['status'] for row in first['phases'][3:]], ['awaiting_review'] * 4)
        approvals = tuple(approve(plan, row['id'], first) for row in first['phases'][3:])
        last = executor.run(plan, self.root / 'result', resume=True, approvals=approvals)
        self.assertEqual(last['status'], 'passed')
        self.assertEqual(first['phases'][2]['artifacts'], last['phases'][2]['artifacts'])
        self.assertEqual(first['phases'][2]['started_at'], last['phases'][2]['started_at'])

    def test_journey_imports_remain_headless(self):
        result = subprocess.run([sys.executable, '-c',
            'import sys;import build_manager.journeys;from build_manager import Plan;'
            'assert not any(n.startswith(("PySide6", "bpy", "mobile")) for n in sys.modules)'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_approval_then_unknown_preserves_other_destination(self):
        plan = integrated(self.root, fail_delivery=True)
        executor = Executor(resource_directory=self.root / 'resources')
        first = executor.run(plan, self.root / 'result')
        second = executor.run(plan, self.root / 'result', resume=True, approvals=(approve(plan, 'testflight', first),))
        self.assertEqual(second['phases'][-1]['status'], 'passed')
        self.assertFalse((self.root / 'firebase.json').exists())
        third = executor.run(plan, self.root / 'result', resume=True, approvals=(approve(plan, 'firebase', second),))
        self.assertEqual(third['status'], 'unknown')
        self.assertEqual(third['phases'][-1]['status'], 'passed')
        before = (self.root / 'firebase.json').stat().st_mtime_ns
        blocked = executor.run(plan, self.root / 'result', resume=True)
        self.assertEqual(blocked['status'], 'unknown')
        self.assertIn('reconciliation', blocked['error'])
        self.assertEqual((self.root / 'firebase.json').stat().st_mtime_ns, before)

    def test_legacy_plan_serialization_keeps_original_identity(self):
        plan = Plan('Fixture', 'Test', {}, (Phase('test', (sys.executable, '-c', 'pass'), str(self.root)),), str(self.root))
        original = asdict(plan); original.pop('journey')
        for phase in original['phases']:
            phase.pop('waits_for')
            phase.pop('label')
            phase.pop('description')
            phase.pop('section')
            phase.pop('test_files')
            phase.pop('retry_exit_codes')
            phase.pop('retry_delay')
            phase.pop('reuse_key')
            phase.pop('approval_required')
            phase.pop('reuse_probe')
        self.assertEqual(plan.identity, hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest())

    def test_step_display_metadata_round_trips_and_changes_review_identity(self):
        phase = Phase('build', (sys.executable, '-V'), str(self.root), effect='build',
                      label='Build Release archive', description='Shared by two exports')
        plan = Plan('Fixture', 'Build', {}, (phase,), str(self.root))
        self.assertEqual(Plan.from_data(plan.data()), plan)
        self.assertNotEqual(plan.identity, replace(plan, phases=(replace(phase, label='Different build'),)).identity)

    def test_isolated_bridge_receives_one_intent_and_cli_writes_same_journey(self):
        root = self.root
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True)
        python = '.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python'
        descriptor = dict(schema=1, adapter_api=1, project_id='fixture', name='Fixture', interpreter=python,
                          bridge='bridge.py', capabilities=CAPABILITIES, journey=CAPABILITY)
        (root / 'build-project.json').write_text(json.dumps(descriptor))
        plan_data = integrated(root).data()
        (root / 'fixture-plan.json').write_text(json.dumps(plan_data))
        (root / 'bridge.py').write_text('''import json,sys
from pathlib import Path
request=json.load(sys.stdin)
assert request['action']=='journey_plan'
assert request['values']['intent']['platforms']==['android','ios']
print(json.dumps(dict(schema=1,result=json.loads(Path('fixture-plan.json').read_text()))))
''')
        registry = Registry(root / 'private'); key = registry.add(root); registry.trust(key)
        bridge = ProjectBridge(registry, key)
        plan = bridge.make_journey('deliver', ['android', 'ios'], ['firebase', 'testflight'])
        self.assertEqual(plan.adapter['checkout'], str(root.resolve()))
        # cli.main is also the installed console entrypoint.
        command = [sys.executable, '-c', 'from build_manager.cli import main;raise SystemExit(main())',
                   '--registry', str(registry.directory), 'journey', '--project', key, '--goal', 'deliver',
                   '--platform', 'android', '--platform', 'ios', '--destination', 'firebase',
                   '--destination', 'testflight', '--output', str(root / 'planned.json')]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Plan.load(root / 'planned.json').identity, plan.identity)

    def test_persistence_rejects_nested_secrets_and_checkout_credentials(self):
        for value in ({'auth.github_token': 'synthetic'}, {'nested': {'password': 'synthetic'}},
                      {'reference': '-----BEGIN PRIVATE KEY-----'}, {'reference': 'ghp_' + 'x' * 36}):
            with self.assertRaises(ValueError):
                reject_secrets(value)
        reject_secrets({'auth.github_reference': 'GH_TOKEN'})
        with patch.dict(os.environ, {'FIXTURE_API_KEY': 'synthetic-api-credential'}):
            with self.assertRaises(ValueError):
                reject_secrets({'otherwise_innocent': 'synthetic-api-credential'})
            from build_manager.redaction import Redactor
            self.assertNotIn('synthetic-api-credential', Redactor()('request failed synthetic-api-credential'))
        (self.root / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'outside Git'):
            protected_reference(self.root / 'ignored-signing.p8')
        plan = integrated(self.root)
        with self.assertRaises(ValueError):
            replace(plan, settings={'auth': {'password': 'synthetic'}}).save(self.root / 'unsafe.json')
        self.assertFalse((self.root / 'unsafe.json').exists())
