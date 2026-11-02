"""Migration, hand edits, checkout identity and cross-project discovery."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.bridge import ProjectBridge
from build_manager.profiles import save_profile
from build_manager.registry import Registry
from build_manager.settings import SettingsStore


class ConfigurationFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.registry = Registry(self.root)
        self.descriptor = {'project_id': 'sample', 'journey': {'destinations': {
            'phones': {'recipient_field': 'targets', 'platforms': ['android']}}}}
        self.row = dict(root=str(self.root), name='Same name', project_id='sample',
                        descriptor='digest', selections={}, presets={'Lab': {
                            'run_overrides': {'targets': '["Serial:5555"]'}}})
        self.legacy = dict(selected='two', projects={'one': self.row, 'two': self.row})
        self.expected = json.loads(json.dumps(self.legacy))
        self.expected['projects']['two']['name'] = 'Same name - ' + self.root.name
        save_profile(self.root / 'registry.json', self.legacy, allowed=self.legacy)

    def test_migration_preserves_identity_and_workspace_edits(self):
        with patch('build_manager.registry.read_project_descriptor', return_value=(self.descriptor, 'digest')):
            self.assertEqual(self.registry.read(), self.expected)
        layout = self.root / 'configuration'
        catalog = layout / 'devices/android.ini'
        self.assertIn('Serial:5555 = Serial:5555', catalog.read_text())
        catalog.write_text('[devices]\nSerial:5555 = Lab phone (100%)\nOther = Spare\n')
        bridge = ProjectBridge.__new__(ProjectBridge)
        bridge.run_fields = [dict(id='targets', kind='multiselect')]
        bridge.registry, bridge.descriptor = self.registry, self.descriptor
        bridge.call = lambda *args, **kwargs: {'targets': [dict(id='Serial:5555', label='Cached')]}
        self.assertEqual(bridge.run_choices()['targets'], [
            dict(id='Serial:5555', label='Lab phone (100%)'), dict(id='Other', label='Spare')])
        path = layout / 'projects/Same name/registration.json'
        data = json.loads(path.read_text())
        data['values']['presets']['By hand'] = {'revision': 'main'}
        path.write_text(json.dumps(data))
        self.registry.select('one')
        self.registry.remove('two')
        self.assertIn('By hand', self.registry.read()['projects']['one']['presets'])
        self.assertNotIn('two', self.registry.read()['projects'])
        self.assertEqual(json.loads((self.root/'registry.json').read_text())['values'], self.legacy)

    def test_unique_aliases_and_profile_copy(self):
        profile = self.root / 'projects/one/profile.json'
        save_profile(profile, {'value': 42}, allowed={'value'})
        self.registry.read()
        self.assertEqual((self.registry.path.parent/'Same name/profile.json').read_bytes(), profile.read_bytes())
        descriptor = dict(self.descriptor, name='same NAME')
        with patch('build_manager.registry.read_project_descriptor', return_value=(descriptor, 'digest')):
            with self.assertRaisesRegex(ValueError, 'already registered'):
                self.registry.add(self.root/'another')
            key = self.registry.add(self.root/'another', name='Lab worktree')
            self.assertEqual(self.registry.add(self.root/'another'), key)
        self.assertEqual(self.registry.read()['projects'][key]['name'], 'Lab worktree')
        self.assertTrue((self.registry.path.parent/'Lab worktree/registration.json').is_file())

    def test_failed_migration_never_exposes_partial_tree(self):
        with patch('build_manager.configuration_files.atomic_write_bytes', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.registry.read()
        self.assertFalse((self.root / 'configuration').exists())
        self.assertEqual(self.registry.read(), self.expected)

    def test_compound_edit_publishes_only_when_its_index_saves(self):
        self.registry.read()
        def rename(data):
            for row in data['projects'].values():
                row['trusted'] = True
        def fail_index(path, values, *, allowed):
            if path == self.registry.path:
                raise OSError('interrupted')
            save_profile(path, values, allowed=allowed)
        with patch('build_manager.registry.save_profile', side_effect=fail_index):
            with self.assertRaises(OSError):
                self.registry.mutate(rename)
        self.assertEqual(self.registry.read(), self.expected)
        self.registry.mutate(rename)
        self.assertTrue(all(r['trusted'] for r in self.registry.read()['projects'].values()))

    def test_shared_account_legacy_import_and_reuse(self):
        settings = dict(accounts={'team': dict(provider='github', kind='environment-name',
                        reference='TEAM_GIT_TOKEN')}, projects={'sample': {'accounts': {'github': 'team'}}})
        save_profile(self.root / 'settings.json', settings, allowed=settings)
        store = SettingsStore(self.root)
        store.bind_project_account('another', 'team')
        fields = {'github': {'reference': 'auth.github_reference', 'kind': 'auth.github_kind'}}
        self.assertEqual(store.account_defaults('another', fields), store.account_defaults('sample', fields))
