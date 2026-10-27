"""Trust, environment isolation, registration and private settings contracts."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager.settings import Field,SettingsStore,resolve


class SettingsTests(unittest.TestCase):
    def test_layers_guard_destinations_and_show_origins(self):
        schema={'auth.reference':Field('',account=True),'tools.python':Field('python',machine=True),
                'destination':Field('one'),'app.id':Field('guarded',guarded=True),
                'workers':Field(1,variable='WORKERS')}
        values,origins=resolve(schema,account={'auth.reference':'shared'},machine={'tools.python':'local'},
            profile={'destination':'two'},environment={'WORKERS':'2'},overrides={'workers':3})
        self.assertEqual(values['destination'],'two');self.assertEqual(origins['workers'],'run override')
        for key in ('destination','app.id'):
            with self.assertRaises(ValueError):resolve(schema,account={key:'wrong'})
        with self.assertRaises(ValueError):resolve(schema,overrides={'app.id':'wrong'})

    def test_idempotent_migration_preserves_original_and_failed_validation(self):
        from build_manager.profiles import save_profile
        with TemporaryDirectory() as directory:
            root=Path(directory);old=root/'legacy';save_profile(old,{'group':'one'},allowed={'group'})
            original=old.read_bytes();store=SettingsStore(root/'private')
            self.assertEqual(store.migrate(old,'a',lambda values:None),store.migrate(old,'a',lambda values:None))
            self.assertEqual(old.read_bytes(),original)
            save_profile(old,{'group':'changed'},allowed={'group'})
            with self.assertRaisesRegex(ValueError,'authority'):store.migrate(old,'a',lambda values:None)
            with self.assertRaises(ValueError):store.account('bad',provider='github',reference='-----BEGIN PRIVATE KEY',kind='protected-file')
            with self.assertRaises(ValueError):store.migrate(old,'b',lambda values:(_ for _ in ()).throw(ValueError('invalid')))
            self.assertNotIn('b',store.read()['projects'])

    def test_interrupted_save_and_unknown_schema_preserve_old_settings(self):
        from unittest.mock import patch
        with TemporaryDirectory() as directory:
            store=SettingsStore(directory)
            store.account('first',provider='github',reference='GH_TOKEN',kind='environment-name')
            original=store.path.read_bytes()
            with patch('commonUtils.persistence.atomic.os.replace',side_effect=OSError('interrupted atomic save')):
                with self.assertRaises(OSError):store.account('second',provider='github',reference='OTHER',kind='environment-name')
            self.assertEqual(store.path.read_bytes(),original)
            store.path.write_text('{"schema":99,"values":{}}')
            with self.assertRaisesRegex(ValueError,'schema'):store.save({})
            self.assertEqual(json.loads(store.path.read_text())['schema'],99)

    def test_shared_github_reference_keeps_project_destinations_distinct(self):
        with TemporaryDirectory() as directory:
            store=SettingsStore(directory)
            store.account('owner',provider='github',reference='SHARED_GH_TOKEN',kind='environment-name')
            fields={'github':{'reference':'auth.github_reference','kind':'auth.github_kind'}}
            for project in ('logistics','bluehole'):store.select_account(project,'owner')
            a=store.account_defaults('logistics',fields);b=store.account_defaults('bluehole',fields)
            self.assertEqual(a,b)
            self.assertEqual(a['auth.github_reference'],'SHARED_GH_TOKEN')
            self.assertNotIn('github.repository',a)
