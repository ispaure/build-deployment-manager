"""Exercise asynchronous storage review against real owned fixture directories."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from PySide6.QtWidgets import QApplication, QSpinBox

from build_manager.ui import SettingsDialog
from build_manager.retention import delete_owned, lease, owned_entries


class ManualStorageTests(unittest.TestCase):
    def test_explicit_delete_rechecks_pin_lease_links_and_direct_child_ownership(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builds = root / 'builds'
            builds.mkdir()
            for name in ('1', '2', '3', '4'):
                (builds / name).mkdir()
            outside = root / 'private'
            outside.mkdir()
            (outside / 'key').write_text('synthetic')
            (builds / '5').symlink_to(outside, target_is_directory=True)
            (builds / 'counter.json').write_text('123')
            eligible = lambda p: p.name.isdigit()
            self.assertEqual(len(owned_entries(builds, eligible=eligible)), 4)
            # The list was reviewed before another build started or was pinned.
            (builds / '2/.keep').touch()
            with lease(builds / '3'):
                protected = {row['name']: row['protected'] for row in owned_entries(builds, eligible=eligible)}
                self.assertTrue(protected['2'])
                self.assertTrue(protected['3'])
                result = delete_owned(builds, ['1', '2', '3', '5', 'counter.json'], eligible=eligible)
                self.assertEqual(result['removed'], [str(builds / '1')])
                self.assertEqual(len(result['skipped']), 4)
            self.assertTrue((outside / 'key').is_file())
            self.assertTrue((builds / 'counter.json').is_file())
            self.assertTrue((builds / '4').is_dir())
            with self.assertRaises(ValueError):
                delete_owned(builds, ['../private'], eligible=eligible)
            linked = root / 'linked'
            linked.symlink_to(builds, target_is_directory=True)
            with self.assertRaises(ValueError):
                delete_owned(linked, ['4'], eligible=eligible)


class SettingsAndStorageUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        from PySide6.QtCore import QThreadPool, QCoreApplication, QEvent
        QThreadPool.globalInstance().waitForDone(5000)
        for widget in self.app.topLevelWidgets():
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, dialog):
        deadline = time.monotonic() + 5
        while dialog.busy:
            self.app.processEvents()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.005)

    def test_categories_retain_edits_tooltips_and_bounded_integer_save(self):
        class Project:
            def settings_view(self):
                return {
                    'timing.seconds': dict(section='Timing', label='Wait', value=4, kind='int', minimum=1, maximum=60,
                                           description='Seconds between checks.'),
                    'target.name': dict(section='Destination', value='Friends', description='Existing beta group.'),
                }
            def save_settings(self, values):
                self.saved = values
        project = Project()
        dialog = SettingsDialog(project)
        seconds = dialog.controls['timing.seconds']
        self.assertIsInstance(seconds, QSpinBox)
        seconds.setValue(100)
        self.assertEqual(seconds.value(), 60)
        self.assertIn('Seconds', seconds.toolTip())
        dialog.controls['target.name'].setText('Synthetic group')
        dialog.sidebar.setCurrentItem(dialog.sidebar.topLevelItem(1))
        self.assertEqual(dialog.stack.currentIndex(), 1)
        dialog.sidebar.setCurrentItem(dialog.sidebar.topLevelItem(0))
        self.assertEqual(seconds.value(), 60)
        dialog.save()
        self.assertEqual(project.saved, {'timing.seconds': 60, 'target.name': 'Synthetic group'})
        dialog.close()

    def test_multiline_and_choices_save_values_and_guarded_fields_remain_read_only(self):
        class Project:
            def settings_view(self):
                return {
                    'notes.body': dict(value='Original', kind='multiline'),
                    'vm.scope': dict(value='both', choices=('both', 'ubuntu', 'fedora')),
                    'identity.app': dict(value='guarded', read_only=True),
                }
            def save_settings(self, values):
                self.saved = values
        project = Project()
        dialog = SettingsDialog(project)
        dialog.controls['notes.body'].setPlainText('First line\nSecond line')
        dialog.controls['vm.scope'].setCurrentText('ubuntu')
        self.assertTrue(dialog.controls['identity.app'].isReadOnly())
        dialog.save()
        self.assertEqual(project.saved, {'notes.body': 'First line\nSecond line', 'vm.scope': 'ubuntu'})
