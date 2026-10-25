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
