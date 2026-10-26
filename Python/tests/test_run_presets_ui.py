"""Private project choices and named presets survive manager recreation."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton
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
                    save = next(button for button in panel.findChildren(QPushButton) if button.text() == 'Save preset…')
                    with patch('build_manager.app.QInputDialog.getText', return_value=('Phones', True)):
                        save.click()
                    self.assertIn('Phones', registry.read()['projects'][key]['presets'])
                    picker.items.item(0).setCheckState(Qt.CheckState.Unchecked)
                    load = next(button for button in panel.findChildren(QPushButton) if button.text() == 'Load preset')
                    load.click()
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
                    panel.run_fields.results.put(({'phones': '["tablet-1"]'}, None))
                    panel.run_fields.loaded()
                    panel.run_fields.controls['phones'].set_choices([dict(id='tablet-1', label='Tablet')])
                    self.assertEqual(panel.run_fields.controls['phones'].text(), '["phone-1"]')
                    window.projects.setCurrentIndex(1)
                    self.assertEqual(window.saved_presets.count(), 1)
                    self.assertEqual(window.panel.run_fields.controls['phones'].text(), '[]')
                    window.projects.setCurrentIndex(0)
                    self.assertEqual(window.panel.run_fields.controls['phones'].text(), '["phone-1"]')
                    delete = next(button for button in window.panel.findChildren(QPushButton) if button.text() == 'Delete preset')
                    window.saved_presets.setCurrentIndex(1)
                    delete.click()
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
