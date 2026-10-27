"""Portable automation contracts using isolated adapters and real harmless children."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan
from build_manager.api import ManagerAPI, read_logs, run_plan
from build_manager.cli import main


class CLITests(unittest.TestCase):
    def test_zero_platform_journey_reaches_project_policy_instead_of_parser_rejection(self):
        from build_manager.cli import parser_for_cli
        args = parser_for_cli().parse_args(['journey', '--goal', 'deliver',
            '--destination', 'devices', '--output', 'plan.json'])
        self.assertEqual(args.platforms, [])
        self.assertEqual(args.destinations, ['devices'])

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='manager CLI café ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / 'private'

    def invoke(self, *args, code=0):
        stream = StringIO()
        with redirect_stdout(stream):
            actual = main(['--registry', str(self.registry), *map(str, args)])
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(actual, code, rows)
        self.assertEqual(rows[-1]['cli_schema'], 1)
        return rows[-1]

    def plan(self, *phases, effect='test'):
        plan = Plan('Fixture', 'Check', {'revision': 'literal source'}, tuple(phases),
                    str(self.root / 'workspace'), effect=effect)
        path = self.root / 'prepared plan.json'
        plan.save(path)
        return plan, path

    def phase(self, name, code, **values):
        return Phase(name, (sys.executable, '-c', code), str(self.root), **values)

    def fixture_project(self):
        root = self.root / 'project'
        root.mkdir()
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True)
        interpreter = '.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python'
        descriptor = dict(schema=1, adapter_api=1, project_id='fixture.cli', name='Fixture',
            interpreter=interpreter, bridge='bridge.py', capabilities=dict(
                platforms=['native'], operations=['Check'], backends={'native': ['Local']}),
            run_fields=[dict(id='notes', label='Notes')])
        (root / 'build-project.json').write_text(json.dumps(descriptor))
        (root / 'bridge.py').write_text('''import json, sys
from pathlib import Path
request = json.load(sys.stdin)
Path('adapter-called').touch()
assert 'build_manager' not in sys.modules
if request['action'] == 'plan':
    result = dict(project='Fixture', operation='Check', source=request['values'],
        workspace=str(Path.cwd() / 'workspace'), phases=[dict(id='check',
        argv=[sys.executable, '-c', "print('project child')"], cwd=str(Path.cwd()))])
elif request['action'] == 'settings':
    result = {'notes': {'value': 'project default'}}
else:
    raise RuntimeError('unexpected adapter action')
print(json.dumps(dict(schema=1, result=result)))
''')
        key = self.invoke('add', root)['registration']
        return root, key

    def test_discover_prepare_execute_and_read_project_history(self):
        root, key = self.fixture_project()
        choices = self.invoke('capabilities', '--project', key)
        self.assertEqual(choices['targets']['native']['Check'], ['Local'])
        self.assertFalse((root / 'adapter-called').exists())
        inputs = self.invoke('inputs', '--project', key)
        self.assertEqual(inputs['defaults']['notes'], 'project default')
        (root / 'adapter-called').unlink()
        path = self.root / 'plan.json'
        prepared = self.invoke('plan', '--project', key, '--operation', 'Check', '--target', 'native',
            '--backend', 'Local', '--run-value', 'notes=literal ; $(nothing) = café', '--output', path)
        self.assertTrue((root / 'adapter-called').exists())
        shown = self.invoke('show-plan', path)
        self.assertEqual(shown['identity'], prepared['identity'])
        self.assertEqual(shown['plan']['source']['run_overrides']['notes'], 'literal ; $(nothing) = café')
        self.assertFalse((root / 'workspace').exists())
        output = root / 'test-results/build-manager/example'
        result = self.invoke('run', path, '--output', output, '--expect-identity', prepared['identity'])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(self.invoke('logs', output, '--step', 'check')['text'], 'project child')
        self.assertEqual(self.invoke('status', output)['counts'], {'passed': 1})
        self.assertEqual(self.invoke('history', '--project', key)['runs'][0]['status'], 'passed')

    def test_failure_summary_events_and_bounded_logs(self):
        plan, path = self.plan(self.phase('broken', 'print("x" * 20000); print("compiler failure"); raise SystemExit(7)'),
                              self.phase('blocked', 'raise AssertionError()', dependencies=('broken',)))
        output = self.root / 'failure'
        with patch.dict(os.environ, {'TEST_API_KEY': 'synthetic-private-token'}):
            result = self.invoke('run', path, '--output', output, '--events', code=1)
        self.assertEqual(result['phases'][0]['exit_code'], 7)
        self.assertIn('compiler failure', result['phases'][0]['summary'])
        self.assertEqual(result['phases'][1]['status'], 'skipped')
        tail = self.invoke('logs', output, '--step', 'broken', '--max-bytes', '80', '--tail-lines', '1')
        self.assertTrue(tail['truncated'])
        self.assertEqual(tail['text'], 'compiler failure')
        self.assertLessEqual(tail['bytes_read'], 80)
        self.assertEqual(self.invoke('status', output, '--full')['schema'], 1)

    def test_child_arguments_are_literal_and_timeouts_remain_supervised(self):
        argument = 'spaces café ; $(nothing) = literal'
        phase = Phase('arguments', (sys.executable, '-c', 'import sys; print(sys.argv[1])', argument), str(self.root))
        plan, path = self.plan(phase, self.phase('timeout', 'import time; time.sleep(30)', timeout=.2))
        output = self.root / 'arguments'
        result = self.invoke('run', path, '--output', output, code=1)
        self.assertEqual(result['phases'][1]['status'], 'timeout')
        self.assertEqual(self.invoke('logs', output, '--step', 'arguments')['text'], argument)

    def test_invalid_requests_are_json_and_do_not_launch(self):
        marker = self.root / 'launched'
        plan, path = self.plan(self.phase('check', f'from pathlib import Path; Path({str(marker)!r}).touch()'))
        output = self.root / 'output'
        self.invoke('run', path, '--output', output, '--expect-identity', 'wrong', code=1)
        self.assertFalse(marker.exists())
        self.assertFalse(output.exists())
        self.assertEqual(self.invoke('run', path, code=2)['error']['code'], 'invalid_arguments')
        for values in (['bad'], ['notes=a', 'notes=b']):
            arguments = [item for value in values for item in ('--run-value', value)]
            self.invoke('plan', '--operation', 'Check', '--target', 'native', '--backend', 'Local',
                        *arguments, '--output', path, code=1)
        self.assertFalse(marker.exists())

    def test_delivery_review_identity_resume_and_no_duplicate_effect(self):
        artifact = self.root / 'candidate'
        delivered = self.root / 'delivered'
        plan, path = self.plan(
            self.phase('prepare', f'from pathlib import Path; Path({str(artifact)!r}).write_text("candidate")',
                       artifacts=(str(artifact),)),
            self.phase('deliver', f'from pathlib import Path; p=Path({str(delivered)!r}); assert not p.exists(); p.touch()',
                       dependencies=('prepare',), effect='upload'))
        output = self.root / 'delivery'
        self.invoke('run', path, '--output', output, code=3)
        self.assertFalse(delivered.exists())
        review = self.invoke('review', output)
        digest = review['approvals'][0]['identity']
        self.invoke('resume', output, '--approval-identity', 'deliver=' + digest, code=1)
        self.invoke('resume', output, '--confirm', '--approval-identity', 'deliver=wrong', code=1)
        self.assertFalse(delivered.exists())
        result = self.invoke('resume', output, '--confirm', '--approval-identity', 'deliver=' + digest)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(delivered.exists())
        self.invoke('resume', output)
        self.assertEqual(self.invoke('review', output)['approvals'], [])

    def test_changed_artifact_and_unknown_effect_cannot_be_retried(self):
        artifact = self.root / 'candidate'
        plan, path = self.plan(
            self.phase('prepare', f'from pathlib import Path; Path({str(artifact)!r}).write_text("candidate")',
                       artifacts=(str(artifact),)),
            self.phase('deliver', 'raise SystemExit(9)', dependencies=('prepare',), effect='upload'))
        output = self.root / 'delivery'
        self.invoke('run', path, '--output', output, code=3)
        digest = self.invoke('review', output)['approvals'][0]['identity']
        artifact.write_text('changed')
        self.invoke('review', output, code=1)
        self.invoke('resume', output, '--confirm', '--approval-identity', 'deliver=' + digest, code=1)
        artifact.write_text('candidate')
        self.assertEqual(self.invoke('resume', output, '--confirm', '--approval-identity', 'deliver=' + digest,
                                     code=1)['status'], 'unknown')
        attempts = self.invoke('status', output, '--full')['attempts']
        result = self.invoke('resume', output, '--confirm', code=1)
        self.assertIn('reconciliation', result['error']['message'])
        self.assertEqual(self.invoke('status', output, '--full')['attempts'], attempts)

    def test_external_plan_needs_confirmation_before_creating_output(self):
        plan, path = self.plan(self.phase('external', 'pass'), effect='dispatch')
        output = self.root / 'external'
        self.invoke('run', path, '--output', output, code=1)
        self.assertFalse(output.exists())

    def test_saved_presets_share_gui_registry_and_start_by_project_name(self):
        root, key = self.fixture_project()
        choices = dict(operation='Check', platform='native', backend='Local', revision='working-tree',
                       run_overrides={'notes':'saved notes'}, goal='advanced')
        source = self.root / 'choices.json'; source.write_text(json.dumps(choices))
        self.invoke('save-preset', 'Everyday', '--project', 'Fixture', '--file', source)
        self.assertEqual(self.invoke('presets', '--project', 'fixture.cli')['saved']['Everyday'], choices)
        self.invoke('save-preset', 'Everyday', '--project', key, '--file', source, code=1)
        self.invoke('save-preset', 'Everyday', '--project', key, '--file', source, '--replace')
        path = self.root / 'preset.json'
        self.invoke('plan', '--project', 'Fixture', '--preset', 'Everyday', '--output', path)
        self.assertEqual(Plan.load(path).source['run_overrides'], {'notes':'saved notes'})
        output = self.root / 'preset-run'
        self.assertEqual(self.invoke('start', '--project', 'Fixture', '--preset', 'Everyday',
                                    '--output', output)['status'], 'passed')
        self.invoke('start', '--project', key, '--preset', 'Everyday', '--output', output, code=1)
        self.invoke('plan', '--project', key, '--preset', 'missing', '--output', path, code=1)
        self.invoke('plan', '--project', key, '--preset', 'Everyday', '--backend', 'Local', '--output', path, code=1)

    def test_journey_presets_use_selected_platforms_hosts_and_inputs(self):
        root, key = self.fixture_project()
        api = ManagerAPI(self.registry)
        choices = dict(goal='deliver', selected_platforms=['native'], selected_destinations=['devices'],
                       platform_backends={'native':'Local'}, run_overrides={'notes':'exact saved value'},
                       revision='HEAD', platform='obsolete-hidden-value', operation='obsolete-hidden-value')
        api.save_preset('Delivery', choices, project=key)
        plan, _ = self.plan(self.phase('check', 'print("ok")'))
        with patch('build_manager.bridge.ProjectBridge.__init__', return_value=None), \
                patch('build_manager.bridge.ProjectBridge.make_journey', return_value=plan) as make:
            from build_manager.bridge import ProjectBridge
            bridge = ProjectBridge(None)
            bridge.key=key; bridge.row={'presets':{'Delivery':choices}}; bridge.workflow_presets={}
            bridge.platforms=('native',); bridge.journey_capability={'platforms':{'native':{'backend':'Local'}}}
            with patch.object(api, '_project', return_value=bridge):
                self.assertEqual(api.prepare_preset('Delivery').identity, plan.identity)
        self.assertEqual(make.call_args.args, ('deliver', ['native'], ['devices']))
        self.assertEqual(make.call_args.kwargs['backends'], {'native':'Local'})
        self.assertEqual(make.call_args.kwargs['revision'], 'HEAD')
        self.assertEqual(make.call_args.kwargs['run_overrides'], {'notes':'exact saved value'})

    def test_engine_change_needs_bound_review_and_preserves_passed_gate_provenance(self):
        from build_manager.identity import runtime_identity, engine_review_identity
        from build_manager.api import review_run
        marker = self.root / 'once'
        plan, path = self.plan(self.phase('gate', 'print("validated")'),
            self.phase('retry', f'from pathlib import Path; p=Path({str(marker)!r}); exists=p.exists(); p.touch(); raise SystemExit(0 if exists else 7)',
                       dependencies=('gate',)))
        output = self.root / 'engine-change'
        first = run_plan(path, output)
        current = runtime_identity()
        current['manager'] = dict(current['manager'], fingerprint='changed-engine')
        with patch('build_manager.identity.runtime_identity', return_value=current):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                run_plan(path, output, resume=True)
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                run_plan(path, output, resume=True, engine_review='stale')
            review = review_run(output)['engine_change']
            self.assertEqual(review['identity'], engine_review_identity(first['engine'], current))
            result = run_plan(path, output, resume=True, engine_review=review['identity'])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['engine_history'][0]['previous'], first['engine'])
        self.assertEqual(result['engine_history'][0]['retained_phases'], ['gate'])
        self.assertEqual(result['phases'][0]['started_at'], first['phases'][0]['started_at'])

    def test_running_log_is_readable_before_phase_completion(self):
        plan, path = self.plan(self.phase('check', 'print("live checkpoint", flush=True)'))
        output = self.root / 'active'
        observed = []
        def event(value):
            if value.get('type') == 'output':
                observed.append(read_logs(output, 'check')['text'])
        report = run_plan(path, output, event=event)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(observed, ['live checkpoint'])

    def test_log_paths_and_sizes_are_validated(self):
        plan, path = self.plan(self.phase('check', 'print("hello")'))
        output = self.root / 'output'
        self.invoke('run', path, '--output', output)
        for step in ('../private', 'missing'):
            self.invoke('logs', output, '--step', step, code=1)
        for args in (('--max-bytes', '65537'), ('--tail-lines', '0')):
            self.invoke('logs', output, '--step', 'check', *args, code=1)
        report_path = output / 'result.json'
        report = json.loads(report_path.read_text())
        report['phases'][0]['log'] = '../outside.log'
        report_path.write_text(json.dumps(report))
        self.invoke('logs', output, '--step', 'check', code=1)
        if os.name != 'nt':
            report['phases'][0]['log'] = 'check.log'
            report_path.write_text(json.dumps(report))
            (output / 'check.log').unlink()
            (output / 'check.log').symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'run directory'):
                read_logs(output, 'check')

    def test_errors_and_logs_redact_inherited_credentials(self):
        token = 'synthetic-private-token-12345'
        with patch.dict(os.environ, {'TEST_API_KEY': token}):
            plan, path = self.plan(self.phase('secret', 'import os; print(os.environ["TEST_API_KEY"]); raise SystemExit(1)'))
            output = self.root / 'secret'
            self.assertNotIn(token, json.dumps(self.invoke('run', path, '--output', output, code=1)))
            self.assertNotIn(token, self.invoke('logs', output, '--step', 'secret')['text'])
            self.assertNotIn(token, json.dumps(self.invoke('show-plan', self.root / token, code=1)))

    def test_python_api_and_real_module_entrypoints_are_headless(self):
        plan, path = self.plan(self.phase('hello', 'print("hello")'))
        result = run_plan(plan, self.root / 'api', expected_identity=plan.identity)
        self.assertEqual(result['status'], 'passed')
        self.assertIsInstance(ManagerAPI(self.registry).registry.read(), dict)
        for module, args in (('build_manager.cli', ['show-plan', str(path)]),
                             ('build_manager', [str(path), '--output', str(self.root / 'legacy')])):
            process = subprocess.run([sys.executable, '-m', module, *args], text=True, capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(all(isinstance(json.loads(line), dict) for line in process.stdout.splitlines()))
        process = subprocess.run([sys.executable, '-c',
            'import sys; from build_manager.api import ManagerAPI; import build_manager.cli; '
            'assert not any(k.startswith(("PySide6", "PyQt", "Logistics")) for k in sys.modules)'],
            text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_editable_console_resolves_pinned_dependency_from_foreign_cwd(self):
        environment = dict(os.environ)
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONHOME', None)
        decoy = self.root / 'commonUtils'
        decoy.mkdir()
        (decoy / '__init__.py').write_text('raise AssertionError("foreign dependency must not load")')
        console = Path(sysconfig.get_path('scripts')) / ('build-manager.exe' if os.name == 'nt' else 'build-manager')
        self.assertTrue(console.is_file(), 'Run with the installed manager interpreter')
        process = subprocess.run([str(console), '--registry', str(self.registry), 'list'],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['projects'], {})
        code = ('from pathlib import Path; import build_manager, commonUtils; '
                'assert Path(commonUtils.__file__).resolve() == '
                'Path(build_manager.__file__).resolve().parents[1] / "commonUtils/__init__.py"')
        process = subprocess.run([sys.executable, '-c', code], cwd=self.root, env=environment,
                                 text=True, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)

    @unittest.skipIf(os.name == 'nt', 'POSIX signal; native Windows cancellation needs acceptance')
    def test_sigterm_cancels_owned_child_and_retains_outcome(self):
        plan, path = self.plan(self.phase('wait', 'import time; print("ready", flush=True); time.sleep(30)'))
        output = self.root / 'cancel'
        process = subprocess.Popen([sys.executable, '-m', 'build_manager.cli', 'run', str(path),
            '--output', str(output), '--events'], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Readiness comes from the owned child, not a scheduling delay.
            from concurrent.futures import ThreadPoolExecutor
            def ready():
                for line in process.stdout:
                    value = json.loads(line)
                    if value.get('event', {}).get('type') == 'output':
                        return
                raise AssertionError('Child exited before readiness')
            with ThreadPoolExecutor() as pool:
                future = pool.submit(ready)
                try:
                    future.result(timeout=15)
                except Exception:
                    process.kill()
                    raise
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 130, stderr)
            self.assertEqual(json.loads(stdout.splitlines()[-1])['status'], 'cancelled')
            self.assertEqual(self.invoke('status', output)['status'], 'cancelled')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
