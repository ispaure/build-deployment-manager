"""Private project choices and named presets survive manager recreation."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from build_manager.app import ManagerWindow
from build_manager.registry import Registry
import test_recipient_ui


class RunPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_restart_presets_and_late_defaults_preserve_specific_devices(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            registry = Registry(root / 'private')
            for name in ('one', 'two'):
                checkout = root / name
                checkout.mkdir()
                (checkout / 'build-project.json').write_text(json.dumps(dict(schema=1, adapter_api=1,
                    project_id=name, name=name, interpreter='.venv/bin/python', bridge='bridge.py',
                    capabilities=dict(platforms=['android'], operations=['Test']))))
                registry.add(checkout)
            key = registry.read()['selected']
            def bridge(store, selected):
                project = test_recipient_ui.RecipientUITests.project(self, root)
                project.row = store.read()['projects'][selected]
                project.run_options = {'verbose': dict(label='Verbose', default=False)}
                return project
            with patch('build_manager.app.ProjectBridge', side_effect=bridge):
                window = ManagerWindow(registry)
                panel = window.panel
                try:
                    panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
                    panel.platform_checks['android'].setChecked(True)
                    panel.destination_checks['phones'].setChecked(True)
                    picker = panel.run_fields.controls['phones']
                    picker.set_choices([dict(id='phone-1', label='Phone')])
                    picker.items.item(0).setCheckState(Qt.CheckState.Checked)
                    panel.build_override.setValue(42)
                    panel.run_controls['verbose'].setChecked(True)
                    panel.revision.setText('HEAD')
                    expected = panel.choices()
                    self.assertEqual(expected['run_overrides'], {'phones': '["phone-1"]'})
                    panel.run_fields.results.put(({}, None))
                    panel.run_fields.loaded()
                    with patch('build_manager.app.QInputDialog.getText', return_value=('Phones', True)):
                        window.preset_actions['Save preset…'].trigger()
                    self.assertIn('Phones', registry.read()['projects'][key]['presets'])
                    picker.items.item(0).setCheckState(Qt.CheckState.Unchecked)
                    window.saved_presets.activated.emit(window.saved_presets.currentIndex())
                    self.assertEqual(panel.choices(), expected)
                    self.assertIsNone(panel.plan)
                    self.assertFalse(panel.start.isEnabled())
                finally:
                    window.close()
                    self.app.processEvents()
                window = ManagerWindow(Registry(registry.directory))
                try:
                    panel = window.panel
                    self.assertEqual(panel.choices(), expected)
                    self.assertEqual(window.saved_presets.currentData(), 'Phones')
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                    panel.run_fields.results.put(({'phones': '["tablet-1"]'}, None))
                    panel.run_fields.loaded()
                    panel.run_fields.controls['phones'].set_choices([dict(id='tablet-1', label='Tablet')])
                    self.assertEqual(panel.run_fields.controls['phones'].text(), '["phone-1"]')
                    window.projects.setCurrentIndex(1)
                    self.assertEqual(window.saved_presets.count(), 1)
                    self.assertEqual(window.panel.run_fields.controls['phones'].text(), '[]')
                    window.projects.setCurrentIndex(0)
                    self.assertEqual(window.panel.run_fields.controls['phones'].text(), '["phone-1"]')
                    window.saved_presets.setCurrentIndex(1)
                    window.preset_actions['Delete preset'].trigger()
                    self.assertEqual(registry.read()['projects'][key]['presets'], {})
                    self.assertFalse((root / 'one' / 'registry.json').exists())
                    if os.name != 'nt':
                        self.assertEqual(registry.path.stat().st_mode & 0o777, 0o600)
                finally:
                    window.close()
                    self.app.processEvents()

    def test_presets_reject_invalid_values_and_secrets(self):
        with TemporaryDirectory() as directory:
            store = Registry(directory)
            store.mutate(lambda data: data['projects'].update(example=dict(root=directory,
                project_id='example', name='Example', descriptor='digest')))
            for choices in ({'build_override': True}, {'run_options': {'verbose': 'yes'}},
                            {'run_overrides': {'notes': 'Bearer synthetic-secret'}}, {'unknown': 'x'}):
                with self.assertRaises(ValueError):
                    store.save_preset('example', 'Invalid', choices)
            store.selections('example', {'revision': 'HEAD'})
            store.save_preset('example', 'Legacy-compatible', {'revision': 'HEAD'})
            self.assertEqual(store.read()['projects']['example']['selections'], {'revision': 'HEAD'})

    def test_reopen_recognizes_sparse_preset_and_tracks_its_explicit_choices(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build-project.json').write_text(json.dumps(dict(schema=1, adapter_api=1,
                project_id='example', name='Example', interpreter='.venv/bin/python', bridge='bridge.py',
                capabilities=dict(platforms=['android'], operations=['Test']))))
            registry = Registry(root / 'private')
            key = registry.add(root)
            choices = dict(goal='deliver', revision='HEAD', selected_platforms=['android'],
                selected_destinations=['phones'], platform_backends={'android': 'local'},
                run_overrides={'phones': '["phone-1"]'})
            registry.save_preset(key, 'Phones', choices)
            def bridge(store, selected):
                project = test_recipient_ui.RecipientUITests.project(self, root)
                project.row = store.read()['projects'][selected]
                project.run_options = {'verbose': dict(label='Verbose', default=False)}
                return project
            with patch('build_manager.app.ProjectBridge', side_effect=bridge):
                window = ManagerWindow(registry)
                try:
                    window.saved_presets.setCurrentIndex(window.saved_presets.findData('Phones'))
                    window.saved_presets.activated.emit(window.saved_presets.currentIndex())
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                finally:
                    window.close()
                    self.app.processEvents()
                window = ManagerWindow(Registry(registry.directory))
                try:
                    self.assertEqual(window.saved_presets.currentData(), 'Phones')
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                    window.panel.revision.setText('another-revision')
                    self.assertIn('Modified', window.saved_presets.currentText())
                    self.assertEqual(registry.read()['projects'][key]['presets']['Phones'], choices)
                finally:
                    window.close()
                    self.app.processEvents()

    def test_reopen_matches_older_preset_with_new_inherited_run_field(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build-project.json').write_text(json.dumps(dict(schema=1, adapter_api=1,
                project_id='example', name='Example', interpreter='.venv/bin/python', bridge='bridge.py',
                capabilities=dict(platforms=['android'], operations=['Test']))))
            registry = Registry(root / 'private')
            key = registry.add(root)
            added_fields = []
            def bridge(store, selected):
                project = test_recipient_ui.RecipientUITests.project(self, root)
                project.row = store.read()['projects'][selected]
                project.run_fields += added_fields
                return project
            with patch('build_manager.app.ProjectBridge', side_effect=bridge):
                window = ManagerWindow(registry)
                try:
                    window.panel.run_fields.results.put(({}, None))
                    window.panel.run_fields.loaded()
                    with patch('build_manager.app.QInputDialog.getText', return_value=('Phones', True)):
                        window.preset_actions['Save preset…'].trigger()
                    # Select the saved preset as in the reported quit/reopen sequence.
                    window.saved_presets.activated.emit(window.saved_presets.currentIndex())
                finally:
                    window.close()
                    self.app.processEvents()
                added_fields.append(dict(id='connection', label='Connection', kind='choice',
                    destinations=['phones'], options={'usb': 'USB', 'wifi': 'Wi-Fi'}, default='usb'))
                window = ManagerWindow(Registry(registry.directory))
                try:
                    panel = window.panel
                    self.assertEqual(window.saved_presets.currentData(), 'Phones')
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                    while not panel.run_fields.results.empty():
                        panel.run_fields.loaded()
                    panel.run_fields.results.put(({'connection': 'wifi'}, None))
                    panel.run_fields.loaded()
                    self.assertEqual(panel.run_fields.controls['connection'].text(), 'wifi')
                    self.assertEqual(window.saved_presets.currentData(), 'Phones')
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                    panel.run_fields.controls['connection'].setText('usb')
                    self.assertIn('Modified', window.saved_presets.currentText())
                    self.assertEqual(registry.read()['projects'][key]['selections']['run_overrides']['connection'], 'usb')
                finally:
                    window.close()
                    self.app.processEvents()
                window = ManagerWindow(Registry(registry.directory))
                try:
                    self.assertIsNone(window.saved_presets.currentData())
                    self.assertEqual(window.panel.run_fields.controls['connection'].text(), 'usb')
                finally:
                    window.close()
                    self.app.processEvents()

    def test_sparse_preset_inherits_new_workflow_option_without_modified_label(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build-project.json').write_text(json.dumps(dict(schema=1, adapter_api=1,
                project_id='example', name='Example', interpreter='.venv/bin/python', bridge='bridge.py',
                capabilities=dict(platforms=['android'], operations=['Test']))))
            registry = Registry(root / 'private')
            key = registry.add(root)
            registry.save_preset(key, 'Older', dict(goal='deliver', revision='HEAD',
                selected_platforms=['android'], selected_destinations=['phones']))
            def bridge(store, selected):
                project = test_recipient_ui.RecipientUITests.project(self, root)
                project.row = store.read()['projects'][selected]
                project.run_fields.append(dict(id='reuse', label='Reuse', kind='choice',
                    options={'on': 'On', 'off': 'Off'}, default='on', workflow_option=True))
                return project
            with patch('build_manager.app.ProjectBridge', side_effect=bridge):
                window = ManagerWindow(registry)
                try:
                    window.saved_presets.setCurrentIndex(window.saved_presets.findData('Older'))
                    window.saved_presets.activated.emit(window.saved_presets.currentIndex())
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                    control = window.panel.run_fields.controls['reuse']
                    control.setText('off')
                    self.assertIn('Modified', window.saved_presets.currentText())
                    control.setText('on')
                    self.assertNotIn('Modified', window.saved_presets.currentText())
                finally:
                    window.close()
                    self.app.processEvents()
