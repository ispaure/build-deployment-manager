"""Exercise the project settings journey with a disposable adapter and profile."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from build_manager.bridge import ProjectBridge
from build_manager.profiles import load_profile, save_profile
from build_manager.providers import SETTING_HELP
from build_manager.registry import Registry
from build_manager.settings import Field, SettingsStore, resolve, validate_settings_resets
from build_manager.settings_ui import SettingsDialog


SCHEMA = {
    'testflight.app_id': Field('123456789'),
    'testflight.external_group': Field('Default Apple group', variable='FIXTURE_APPLE_GROUP'),
    'firebase.app_id': Field('1:1234567890:android:0a1b2c3d4e5f67890'),
    'firebase.group': Field('default-firebase-group', variable='FIXTURE_FIREBASE_GROUP'),
    'firebase.release_notes': Field('Default notes'),
    'tools.blender': Field('', machine=True),
    'auth.github_reference': Field('GH_TOKEN', account=True),
    'signing.app_profile': Field(''),
}
PROTECTED = {'testflight.app_id', 'auth.github_reference', 'signing.app_profile'}


class ProjectSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def open_settings(self):
        dialog = SettingsDialog(self.project)
        self.addCleanup(self.close, dialog)
        dialog.show()
        self.wait(dialog)
        self.assertFalse(dialog.retry.isVisible(), dialog.status.text())
        return dialog

    def close(self, dialog):
        from shiboken6 import isValid
        if isValid(dialog):
            dialog.dirty = False
            dialog.reject()
            self.app.processEvents()

    def wait(self, dialog):
        for _ in range(150):
            if not dialog.busy:
                break
            QTest.qWait(10)
        self.assertFalse(dialog.busy)

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        checkout = root / 'checkout'
        checkout.mkdir()
        (checkout / 'bridge.py').touch()
        (checkout / 'build-project.json').write_text(json.dumps({
            'schema': 1, 'adapter_api': 1, 'project_id': 'org.example.settings',
            'name': 'Settings fixture', 'bridge': 'bridge.py', 'interpreter': '.venv/bin/python',
            'capabilities': {'platforms': ['ios', 'android'], 'operations': ['Test'],
                             'backends': {'ios': ['Local'], 'android': ['Local']}},
        }))
        registry = Registry(root / 'configuration')
        self.key = registry.add(checkout)
        self.preset = {'operation': 'Test', 'platform': 'ios', 'backend': 'Local'}
        registry.save_preset(self.key, 'Existing preset', self.preset)
        self.profile = registry.path.parent / 'Settings fixture' / 'profile.json'
        store = SettingsStore(registry.directory)
        store.save_account_reference('test-account', provider='github', reference='TEST_GITHUB_TOKEN',
                                     kind='environment-name')
        store.bind_project_account('org.example.settings', 'test-account')
        self.account_before = store.path.read_bytes()
        self.store = store
        self.project = ProjectBridge(registry, self.key)
        self.initial = {
            'firebase.group': 'old-group', 'firebase.release_notes': 'Old notes',
            'testflight.external_group': 'Saved Apple group',
            'signing.app_profile': str(root / 'placeholder.mobileprovision'),
        }
        save_profile(self.profile, self.initial, allowed=SCHEMA)
        self.environment = {}
        self.requests = []
        # Exercise the normal ProjectBridge load, validation and store methods.
        # This fixture substitutes the project-owned protocol handlers.
        self.project.call = self.adapter_call

    def adapter_call(self, action, **request):
        profile = load_profile(self.profile)
        account = self.store.account_defaults('org.example.settings', {'github': {
            'reference': 'auth.github_reference', 'kind': 'auth.github_kind'}})
        account.pop('auth.github_kind', None)
        def effective(overrides):
            return resolve(SCHEMA, profile=overrides, environment=self.environment, account=account)
        values, origins = effective(profile)
        rows = {}
        for name, value in values.items():
            entry = dict(value=value, origin=origins[name], read_only=name in PROTECTED - {'signing.app_profile'})
            if name in {'testflight.external_group', 'firebase.group', 'firebase.release_notes'}:
                entry['section'] = 'Defaults for new runs'
            if name not in PROTECTED:
                fallback, fallback_origins = effective({k: v for k, v in profile.items() if k != name})
                entry['reset'] = dict(overridden=name in profile, value=fallback[name], origin=fallback_origins[name])
            rows[name] = entry
        if action == 'settings':
            return rows
        if action != 'save_settings':
            raise AssertionError(action)
        changes, resets = request['changes'], request.get('resets', ())
        validate_settings_resets(rows, changes, resets)
        self.requests.append((changes, resets))
        for name in resets:
            profile.pop(name, None)
        profile.update(changes)
        effective(profile)
        save_profile(self.profile, profile, allowed=SCHEMA)

    def click_button(self, dialog, text):
        button = next(button for button in dialog.findChildren(QPushButton)
                      if button.isVisible() and button.text() == text)
        button.click()

    def test_first_use_help_and_field_reset_across_reopens(self):
        dialog = self.open_settings()
        self.assertEqual(dialog.sidebar.topLevelItem(0).text(0), 'Run defaults')
        dialog.sidebar.setCurrentItem(dialog.sections[('Delivery',)][0])
        self.click_button(dialog, 'TestFlight')
        self.assertEqual(dialog.sidebar.currentItem().text(0), 'TestFlight')
        self.assertTrue(dialog.controls['testflight.app_id'].isReadOnly())
        help_button = next(button for button in dialog.findChildren(QPushButton)
                           if button.accessibleName() == 'Help for App Store Connect Apple ID')
        snapshots = []

        def inspect_help():
            help_dialog = QApplication.activeModalWidget()
            snapshots.append(' '.join(label.text() for label in help_dialog.findChildren(QLabel)))
            self.click_button(help_dialog, 'Apple App Information reference ↗')

            def inspect_guide():
                from commonUtils.ui.markdown import MarkdownViewer
                guide_dialog = QApplication.activeModalWidget()
                viewer = guide_dialog.findChild(MarkdownViewer)
                snapshots.append((viewer.current_path.name, viewer.history[-1]['url'].fragment()))
                QTest.keyClick(guide_dialog, Qt.Key.Key_Escape)

            QTimer.singleShot(0, inspect_guide)
            self.click_button(help_dialog, 'Manager delivery setup guide…')
            QTest.keyClick(help_dialog, Qt.Key.Key_Escape)

        with patch('build_manager.settings_ui.QDesktopServices.openUrl', return_value=True) as source:
            identity = dialog.controls['testflight.app_id']
            identity.setFocus()
            QTest.keyClick(identity, Qt.Key.Key_Tab)
            self.assertIs(self.app.focusWidget(), help_button)
            QTimer.singleShot(0, inspect_help)
            QTest.keyClick(help_button, Qt.Key.Key_Space)
            source.assert_called_once()
            self.assertEqual(source.call_args.args[0].toString(), SETTING_HELP['testflight.app_id'].url)
        self.assertIn('numeric Apple ID', snapshots[0])
        self.assertEqual(snapshots[1], ('delivery-setup.md', 'testflight'))

        self.click_button(dialog, 'Open TestFlight run defaults')
        group = 'testflight.external_group'
        dialog.controls[group].setText('Disposable Apple group')
        dialog.save()
        self.wait(dialog)
        self.assertEqual(self.requests, [({group: 'Disposable Apple group'}, ())])
        self.assertEqual(load_profile(self.profile), self.initial | {group: 'Disposable Apple group'})

        reopened = self.open_settings()
        self.assertEqual(reopened.controls[group].text(), 'Disposable Apple group')
        reopened.reset_buttons[group][0].click()
        self.assertEqual(reopened.controls[group].text(), 'Default Apple group')
        self.assertIn('tracked project default', reopened.origin_labels[group].text())
        self.assertIn(group, load_profile(self.profile))
        reopened.reset_buttons[group][0].click()
        self.assertEqual(reopened.controls[group].text(), 'Disposable Apple group')
        reopened.reset_buttons[group][0].click()
        reopened.save()
        self.wait(reopened)
        self.assertEqual(self.requests[-1], ({}, [group]))
        final = self.open_settings()
        self.assertEqual(final.controls[group].text(), 'Default Apple group')
        self.assertIn('tracked project default', final.origin_labels[group].text())
        self.assertNotIn(group, load_profile(self.profile))

    def test_page_reset_keeps_other_edits_and_protected_references(self):
        self.environment['FIXTURE_FIREBASE_GROUP'] = 'Environment group'
        dialog = self.open_settings()
        dialog.controls['tools.blender'].setText('Disposable Blender path')
        for name in PROTECTED:
            self.assertNotIn(name, dialog.reset_buttons)
        reset = dialog.page_resets[('Run defaults',)]
        dialog.search.setText('group')
        self.assertFalse(reset.isEnabled())
        dialog.search.clear()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            reset.click()
        self.assertEqual(dialog.resets, {})
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            reset.click()
        self.assertEqual(dialog.controls['firebase.group'].text(), 'Environment group')
        self.assertIn('Source: environment', dialog.origin_labels['firebase.group'].text())
        dialog.save()
        self.wait(dialog)
        self.assertEqual(load_profile(self.profile), {
            'tools.blender': 'Disposable Blender path', 'signing.app_profile': self.initial['signing.app_profile']})
        self.assertEqual(self.store.path.read_bytes(), self.account_before)
        self.assertEqual(self.project.registry.read()['projects'][self.key]['presets'],
                         {'Existing preset': self.preset})

        reopened = self.open_settings()
        self.assertEqual(reopened.controls['firebase.group'].text(), 'Environment group')
        self.assertFalse(reopened.reset_buttons['firebase.group'][0].isEnabled())
        self.close(reopened)
        self.environment.clear()
        unmasked = self.open_settings()
        self.assertEqual(unmasked.controls['firebase.group'].text(), 'default-firebase-group')
        self.assertEqual(unmasked.controls['tools.blender'].text(), 'Disposable Blender path')

    def test_legacy_adapter_receives_only_edited_fields(self):
        writer = Mock()
        self.project = SimpleNamespace(settings_view=lambda: {
            'tools.blender': dict(value='Environment Blender', origin='environment BLUEHOLE_BLENDER'),
            'tools.hosted_evidence': dict(value='Old evidence', origin='private project tooling profile'),
            'auth.github_reference': dict(value='TEST_GITHUB_TOKEN', origin='selected shared GitHub account'),
        }, save_settings=writer)
        dialog = self.open_settings()
        self.assertFalse(dialog.reset_buttons)
        self.assertIn('BLUEHOLE_BLENDER', dialog.origin_labels['tools.blender'].text())
        dialog.controls['tools.hosted_evidence'].setText('New disposable evidence')
        dialog.save()
        self.wait(dialog)
        writer.assert_called_once_with({'tools.hosted_evidence': 'New disposable evidence'})
