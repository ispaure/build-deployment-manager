"""Trust, environment isolation, registration and private settings contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
from fixture_directory import TemporaryDirectory
import unittest

from build_manager.registry import Registry,inspect
from build_manager.bridge import ProjectBridge


class RegistryTests(unittest.TestCase):
    def test_bridge_supplies_checkout_specific_private_profile_and_manager_context(self):
        root = self.fixture('context')
        (root / 'bridge.py').write_text('import json,sys; r=json.load(sys.stdin); print(json.dumps(dict(schema=1,result=r)))')
        key = self.registry.add(root)
        result = ProjectBridge(self.registry).call('settings')
        self.assertEqual(result['settings_profile'], str(self.registry.directory / 'projects' / key / 'profile.json'))
        self.assertEqual(result['manager_checkout'], str(Path(__file__).resolve().parents[2]))

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='projects café ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry=Registry(self.root/'private')

    def fixture(self,name):
        root=self.root/name;root.mkdir()
        subprocess.run([sys.executable,'-m','venv','--without-pip',str(root/'.venv')],check=True)
        python='.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python'
        descriptor=dict(schema=1,adapter_api=1,project_id='fixture.'+name,name=name,
            interpreter=python,bridge='bridge.py',capabilities=dict(platforms=['native'],operations=['Check']))
        (root/'build-project.json').write_text(json.dumps(descriptor))
        (root/'bridge.py').write_text('import json,sys;print(json.dumps(dict(schema=1,result=sys.prefix)))')
        return root

    def test_registration_trusts_checkout_and_descriptor_updates(self):
        root = self.fixture('a')
        marker = root / 'executed'
        (root / 'bridge.py').write_text(
            'import json; from pathlib import Path; Path("executed").touch(); '
            'print(json.dumps(dict(schema=1,result="loaded")))')
        key = self.registry.add(root)
        self.assertFalse(marker.exists())
        self.assertTrue(self.registry.read()['projects'][key]['trusted'])
        self.assertEqual(self.registry.add(root), key)
        bridge = ProjectBridge(self.registry, key)
        self.assertEqual(bridge.call('anything'), 'loaded')
        path = root / 'build-project.json'
        path.write_text(path.read_text() + ' ')
        import hashlib
        self.assertEqual(self.registry.resolve(key)[0]['descriptor'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(bridge.call('anything'), 'loaded')

    def test_existing_untrusted_registration_works_without_approval(self):
        root = self.fixture('legacy')
        key = self.registry.add(root)
        self.registry.mutate(lambda data: data['projects'][key].update(trusted=False))
        self.assertIn(str(root), ProjectBridge(self.registry, key).call('prefix'))
        self.assertEqual(self.registry.add(root), key)
        self.assertTrue(self.registry.read()['projects'][key]['trusted'])

    def test_registration_still_rejects_changed_project_identity(self):
        root = self.fixture('identity')
        key = self.registry.add(root)
        path = root / 'build-project.json'
        descriptor = json.loads(path.read_text())
        descriptor['project_id'] = 'different'
        path.write_text(json.dumps(descriptor))
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.registry.resolve(key, trusted=True)
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.registry.add(root)

    def test_two_interpreters_relocate_remove_and_active_switch(self):
        a,b=self.fixture('a'),self.fixture('b')
        ka,kb=self.registry.add(a),self.registry.add(b)
        for key in (ka,kb):self.registry.trust(key)
        self.assertNotEqual(ProjectBridge(self.registry,ka).call('prefix'),ProjectBridge(self.registry,kb).call('prefix'))
        with self.assertRaisesRegex(ValueError,'active'):self.registry.select(kb,active=True)
        moved=self.root/'moved';a.rename(moved);self.registry.locate(ka,moved)
        self.assertTrue(self.registry.resolve(ka)[0]['trusted'])
        self.assertIn(str(moved), ProjectBridge(self.registry, ka).call('prefix'))
        self.registry.remove(kb);self.assertTrue(b.exists())
        descriptor=json.loads((moved/'build-project.json').read_text());descriptor['schema']=9
        (moved/'build-project.json').write_text(json.dumps(descriptor))
        with self.assertRaisesRegex(ValueError,'schema'):inspect(moved)

    def test_malformed_descriptor_stops_before_adapter_execution(self):
        root=self.fixture('broken')
        (root/'build-project.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'object'):inspect(root)

    def test_suite_metadata_is_validated_before_trust_and_selection_is_recorded(self):
        root = self.fixture('suites')
        path = root / 'build-project.json'
        descriptor = json.loads(path.read_text())
        suite = dict(id='portable.contracts', label='Contracts', tier='contracts',
                     platforms=['native'], operations=['Check'])
        descriptor['test_suites'] = [suite, suite]
        path.write_text(json.dumps(descriptor))
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.registry.add(root)
        descriptor['test_suites'] = [suite]
        path.write_text(json.dumps(descriptor))
        key = self.registry.add(root)
        self.registry.trust(key)
        bridge = ProjectBridge(self.registry, key)
        # The fixture bridge has no manager or project imports: it echoes the
        # selected suite into a plain executable plan through the real protocol.
        (root / 'bridge.py').write_text('''import json,sys
from pathlib import Path
values=json.load(sys.stdin)['values']
plan=dict(project='suites',operation='Check',source={'suite':values.get('suite')},
    workspace=str(Path.cwd()/'workspace'),phases=[dict(id='contracts',argv=[sys.executable,'-c','pass'],cwd=str(Path.cwd()))])
print(json.dumps(dict(schema=1,result=plan)))
''')
        plan = bridge.make_plan('Check', 'native', 'Local', suite='portable.contracts')
        self.assertEqual(plan.source['suite'], 'portable.contracts')
        self.assertEqual(plan.adapter['test_suite'], 'portable.contracts')
        from contextlib import redirect_stdout
        from io import StringIO
        from build_manager.cli import main
        output = root / 'selected-plan.json'
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['--registry', str(self.registry.directory), 'plan', '--project', key,
                '--operation', 'Check', '--target', 'native', '--backend', 'Local', '--suite', 'portable.contracts',
                '--output', str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())['adapter']['test_suite'], 'portable.contracts')
        with self.assertRaisesRegex(ValueError, 'suite'):
            bridge.make_plan('Check', 'native', 'Local', suite='unknown')

    def test_settings_bridge_cancellation_timeout_and_checkout_reference_protection(self):
        from threading import Event, Timer
        import time
        root = self.fixture('settings-lifecycle')
        key = self.registry.add(root); self.registry.trust(key)
        bridge = ProjectBridge(self.registry, key)
        (root / 'bridge.py').write_text('import time;time.sleep(20)')
        cancelled = Event(); timer = Timer(.1, cancelled.set); timer.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                bridge.load_settings(cancelled=cancelled.is_set)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 3)
        with self.assertRaisesRegex(ValueError, 'timed out'):
            bridge.call('settings', timeout=.05)
        (root / 'bridge.py').write_text('''import json,sys
request=json.load(sys.stdin)
assert request['action']=='settings', 'writer must not run for an unsafe credential reference'
print(json.dumps(dict(schema=1,result={'auth.signing_reference':dict(value='',kind='reference')})))
''')
        with self.assertRaisesRegex(ValueError, 'outside the project checkout'):
            bridge.store_settings({'auth.signing_reference': str(root / 'ignored.p8')})
        with self.assertRaisesRegex(ValueError, 'secret values'):
            bridge.store_settings({'auth.password': 'synthetic'})

    def test_interpreter_paths_and_environment_names_are_not_credential_files(self):
        root = self.fixture('reference-types')
        key = self.registry.add(root); self.registry.trust(key)
        bridge = ProjectBridge(self.registry, key)
        (root / 'bridge.py').write_text('''import json,sys
request=json.load(sys.stdin)
rows={'tools.desktop_python':dict(value='',kind='reference'),
      'auth.github_reference':dict(value='',kind='reference'),
      'auth.github_kind':dict(value='environment-name')}
print(json.dumps(dict(schema=1,result=rows if request['action']=='settings' else request['values']['changes'])))
''')
        values = {'tools.desktop_python': str(root / '.venv/bin/python'),
                  'auth.github_reference': 'GH_TOKEN', 'auth.github_kind': 'environment-name'}
        self.assertEqual(bridge.store_settings(values), values)
