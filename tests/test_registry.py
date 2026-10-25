"""Trust, environment isolation, registration and private settings contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager.registry import Registry,inspect
from build_manager.bridge import ProjectBridge


class RegistryTests(unittest.TestCase):
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

    def test_inspection_does_not_execute_and_trust_is_explicit(self):
        root=self.fixture('a');key=self.registry.add(root)
        self.assertEqual(self.registry.add(root),key)
        bridge=ProjectBridge(self.registry,key)
        with self.assertRaisesRegex(ValueError,'trust'):bridge.call('anything')
        self.registry.trust(key)
        self.assertIn(str(root),bridge.call('anything'))
        (root/'build-project.json').write_text((root/'build-project.json').read_text()+' ')
        with self.assertRaisesRegex(ValueError,'trust'):bridge.call('anything')

    def test_two_interpreters_relocate_remove_and_active_switch(self):
        a,b=self.fixture('a'),self.fixture('b')
        ka,kb=self.registry.add(a),self.registry.add(b)
        for key in (ka,kb):self.registry.trust(key)
        self.assertNotEqual(ProjectBridge(self.registry,ka).call('prefix'),ProjectBridge(self.registry,kb).call('prefix'))
        with self.assertRaisesRegex(ValueError,'active'):self.registry.select(kb,active=True)
        moved=self.root/'moved';a.rename(moved);self.registry.locate(ka,moved)
        self.assertFalse(self.registry.resolve(ka)[0]['trusted'])
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
