"""Storage requests, sliced rendering and close own their full Qt lifetime."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from build_manager.storage_ui import StorageDialog
from build_manager import retention


class StorageLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.environment = patch.dict(os.environ, COMMONUTILS_STORAGE_ROOT=str(self.root / 'shared'))
        self.environment.start()
        self.dialogs = []
        self.gates = []
        root = self.root
        class Project:
            descriptor = {}
            def __init__(self):
                self.root = root
                self.results_directory = root / 'runs'
            def storage_inventory(self):
                return [dict(row, group='Prepared files') for row in retention.owned_entries(
                    root / 'outputs', eligible=lambda path: (path / '.owned').is_file())]
            def delete_storage(self, selections):
                return retention.delete_owned(root / 'outputs', selections['Prepared files'],
                                              eligible=lambda path: (path / '.owned').is_file())
        self.project = Project()
        output = root / 'outputs/one'
        output.mkdir(parents=True)
        (output / '.owned').touch()
        (output / 'data').write_bytes(b'owned' * 1000)

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        self.wait(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
        for dialog in self.dialogs:
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                dialog.close()
            self.app.processEvents()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.environment.stop()
        self.temporary.cleanup()

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            time.sleep(.002)
            self.assertLess(time.monotonic(), deadline)
        self.app.processEvents()

    def dialog(self):
        dialog = StorageDialog(self.project)
        self.dialogs.append(dialog)
        dialog.show()
        return dialog

    def ready(self):
        dialog = self.dialog()
        self.wait(lambda: not dialog.busy)
        self.assertIsNotNone(dialog.snapshot)
        return dialog

    def delayed_inventory(self):
        entered, release = Event(), Event()
        self.gates.append(release)
        from build_manager.storage_inventory import gather
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(4)
            return gather(*args, **kwargs)
        return entered, release, delayed

    def test_initial_view_is_deferred_and_storage_lists_are_available(self):
        with patch('build_manager.storage_inventory.gather', wraps=__import__(
                'build_manager.storage_inventory', fromlist=['gather']).gather) as gather:
            dialog = StorageDialog(self.project)
            self.dialogs.append(dialog)
            self.assertTrue(dialog.busy)
            gather.assert_not_called()
            dialog.show()
            self.wait(lambda: not dialog.busy)
            self.assertEqual(dialog.table.topLevelItemCount(), 1)
            self.assertEqual(dialog.evidence.topLevelItemCount(), 0)
            self.assertTrue(dialog.table.isEnabled())
            self.assertTrue(dialog.group.isEnabled())
            self.assertFalse(dialog.selected.isEnabled())

    def test_close_during_legacy_read_waits_and_rejects_late_results(self):
        entered, release, delayed = self.delayed_inventory()
        with patch('build_manager.storage_inventory.gather', side_effect=delayed):
            dialog = self.dialog()
            self.wait(entered.is_set)
            dialog.close()
            self.assertTrue(dialog.close_requested)
            self.assertFalse(dialog.closed)
            self.assertTrue(dialog.busy)
            dialog.reload()
            release.set()
            self.wait(lambda: dialog.closed)
            self.assertIsNone(dialog.snapshot)
            self.assertEqual(dialog.table.topLevelItemCount(), 0)

    def test_changed_project_cannot_receive_old_success(self):
        entered, release, delayed = self.delayed_inventory()
        with patch('build_manager.storage_inventory.gather', side_effect=delayed):
            dialog = self.dialog()
            self.wait(entered.is_set)
            dialog.project = SimpleNamespace(root=self.root / 'different', descriptor={})
            release.set()
            self.wait(lambda: not dialog.busy)
            self.assertIsNone(dialog.snapshot)
            self.assertIn('Project changed', dialog.status.text())
            self.assertFalse(dialog.selected.isEnabled())

    def test_cancelled_error_cannot_replace_stopped_state(self):
        entered, release = Event(), Event()
        self.gates.append(release)
        def failed(*args, **kwargs):
            entered.set(); release.wait(4)
            raise ValueError('old failure should not appear')
        with patch('build_manager.storage_inventory.gather', side_effect=failed):
            dialog = self.dialog()
            self.wait(entered.is_set)
            dialog.cancel()
            release.set()
            self.wait(lambda: not dialog.busy)
            self.assertIn('Stopped', dialog.status.text())
            self.assertNotIn('old failure', dialog.status.text())

    def test_delayed_index_keeps_input_responsive_and_cancellation_drains_it(self):
        from commonUtils.filesystem.index import DirectoryCache
        original = DirectoryCache.get
        entered, release = Event(), Event()
        self.gates.append(release)
        def delayed(cache, *args, **kwargs):
            entered.set(); release.wait(4)
            return original(cache, *args, **kwargs)
        with patch.object(DirectoryCache, 'get', delayed):
            dialog = self.dialog()
            self.wait(entered.is_set)
            ticks = []
            timer = QTimer(dialog)
            timer.setInterval(10)
            timer.timeout.connect(lambda: ticks.append(time.monotonic()))
            timer.start()
            dialog.resize(640, 680)
            self.wait(lambda: len(ticks) >= 4)
            self.assertTrue(dialog.table.isEnabled())
            self.assertTrue(dialog.stop.isEnabled())
            dialog.stop.click()
            self.assertTrue(dialog.busy)
            release.set()
            self.wait(lambda: not dialog.busy)
            timer.stop()
            self.assertIn('Stopped', dialog.status.text())
            self.assertFalse(dialog.selected.isEnabled())

    def test_bulk_selection_does_not_delete_and_preview_defaults_to_no(self):
        dialog = self.ready()
        dialog.all.click()
        self.assertEqual(len(dialog.table.selectedItems()), 1)
        self.assertTrue((self.root / 'outputs/one/data').is_file())
        defaults = []
        def decline(box):
            defaults.append(box.defaultButton().text().replace('&', ''))
            return QMessageBox.StandardButton.No
        with patch.object(QMessageBox, 'exec', decline):
            dialog.selected.click()
            self.wait(lambda: not dialog.busy)
        self.assertEqual(defaults, ['No'])
        self.assertIn('No files were removed', dialog.status.text())
        self.assertNotIn('Reading', dialog.status.text())
        self.assertTrue((self.root / 'outputs/one/data').is_file())

    def test_successful_cleanup_clears_deleted_selection_and_details(self):
        dialog = self.ready()
        item = dialog.table.topLevelItem(0)
        dialog.table.setCurrentItem(item)
        item.setSelected(True)
        self.assertIn('outputs/one', dialog.details.toPlainText())
        with patch.object(QMessageBox, 'exec', return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, 'information'):
            dialog.selected.click()
            self.wait(lambda: not dialog.busy)
        self.assertFalse((self.root / 'outputs/one').exists())
        self.assertEqual(dialog.table.topLevelItemCount(), 0)
        self.assertEqual(dialog.details.toPlainText(), '')
        self.assertFalse(dialog.details_button.isEnabled())

    def test_small_window_with_chart_keeps_readable_item_rows_and_states(self):
        dialog = self.ready()
        dialog.resize(640, 680)
        dialog.chart_toggle.click()
        self.app.processEvents()
        self.assertLessEqual(dialog.width(), 640)
        self.assertLessEqual(dialog.height(), 680)
        self.assertGreaterEqual(dialog.table.viewport().height(), 80)
        self.assertGreaterEqual(dialog.table.columnWidth(2), dialog.fontMetrics().horizontalAdvance('Kept for a later run') + 8)
        self.assertTrue(dialog.table.isVisible())
        self.assertFalse(dialog.category_list.isVisible())
        dialog.chart_toggle.click()
        self.assertTrue(dialog.category_list.isVisible())

    def test_close_during_deletion_drains_worker_and_remembers_outcome(self):
        dialog = self.ready()
        entered, release = Event(), Event()
        self.gates.append(release)
        def remove(task):
            entered.set(); release.wait(4)
            return dict(removed=['owned fixture'], skipped=[], failed=[], cancelled=task.cancelled.is_set())
        dialog.start(remove, 'delete', mutation=True)
        self.wait(entered.is_set)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.close()
        self.assertFalse(dialog.closed)
        self.assertTrue(dialog.table.isEnabled())
        with patch.object(QMessageBox, 'information'):
            release.set()
            self.wait(lambda: dialog.closed)
        self.assertEqual(dialog.last_outcome['removed'], ['owned fixture'])
        self.assertTrue(dialog.last_outcome['cancelled'])

    def test_large_render_yields_and_cancel_disables_cleanup(self):
        dialog = self.ready()
        from copy import deepcopy
        row = dialog.snapshot['rows'][0]
        many = []
        for index in range(3000):
            value = deepcopy(row)
            value.update(key=f'{row["key"]}-{index}', path=f'{row["path"]}-{index}', label=f'Output {index}')
            many.append(value)
        dialog.rows = many
        dialog.render()
        self.assertEqual(dialog.table.topLevelItemCount(), 1)  # Old rows retire in bounded slices too.
        dialog.render_slice()
        self.assertLessEqual(dialog.table.topLevelItemCount(), dialog._ROW_BATCH_SIZE)
        self.assertTrue(dialog.busy)
        dialog.cancel()
        self.assertFalse(dialog.busy)
        self.assertFalse(dialog.selected.isEnabled())

    def test_chart_uses_exact_category_list_amounts(self):
        dialog = self.ready()
        dialog.chart_toggle.click()
        self.assertEqual(sum(size for _, size in dialog.chart.items), dialog.snapshot['allocated_bytes'])
        self.assertTrue(dialog.chart_holder.isVisible())
        dialog.resize(620, 650)
        self.app.processEvents()
        self.assertTrue(dialog.table.isEnabled())
        self.assertGreater(dialog.table.viewport().width(), 100)

    def test_category_arrows_return_and_mouse_click_change_the_displayed_filter(self):
        from build_manager.storage_inventory import BUILDS, CACHES
        dialog = self.ready()
        tree = dialog.category_list
        tree.setCurrentItem(tree.topLevelItem(0))
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key.Key_Down)
        self.assertEqual(tree.currentItem().text(0), CACHES)
        QTest.keyClick(tree, Qt.Key.Key_Return)
        self.wait(lambda: not dialog.busy)
        self.assertEqual(dialog.group.currentData(), CACHES)
        self.assertEqual(dialog.table.topLevelItemCount(), 0)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=tree.visualItemRect(tree.topLevelItem(0)).center())
        self.wait(lambda: not dialog.busy)
        self.assertEqual(dialog.group.currentData(), BUILDS)
        self.assertEqual(dialog.table.topLevelItemCount(), 1)
