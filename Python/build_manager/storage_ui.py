"""Review and remove project-owned outputs without blocking the GUI on disk I/O."""
from functools import partial
from queue import Empty, Queue

from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)


class StorageTask(QRunnable):
    def __init__(self, action, results):
        super().__init__()
        self.action, self.results = action, results

    def run(self):
        try:
            self.results.put((self.action(), None))
        except Exception as error:
            self.results.put((None, str(error)))


class StorageDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.rows, self.busy = project, [], False
        self.results = Queue()
        self.setWindowTitle('Clean up builds')
        self.resize(950, 600)
        layout = QVBoxLayout(self)
        note = QLabel('Only manager-owned build outputs, source snapshots and disposable scratch are listed. '
                      'Deleting builds removes their local artifacts; it does not remove published releases. '
                      'Pinned (.keep) and active outputs are protected. Tools, signing files, credentials, '
                      'build counters and installed apps are kept.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.group = QComboBox()
        self.group.addItem('All platforms and storage')
        self.group.currentIndexChanged.connect(self.render)
        layout.addWidget(self.group)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Platform / storage', 'Build / snapshot', 'Protection', 'Location'])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAccessibleName('Owned build outputs')
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.refresh = QPushButton('Refresh')
        self.selected = QPushButton('Delete selected…')
        self.all = QPushButton('Delete all unprotected…')
        self.refresh.clicked.connect(self.reload)
        self.selected.clicked.connect(lambda: self.remove(False))
        self.all.clicked.connect(lambda: self.remove(True))
        for button in (self.refresh, self.selected, self.all):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.completed)
        self.reload()

    def start(self, action, mode):
        self.busy, self.mode = True, mode
        self.update_buttons()
        self.status.setText('Reading owned outputs…' if mode == 'list' else 'Deleting reviewed outputs…')
        QThreadPool.globalInstance().start(StorageTask(action, self.results))
        self.timer.start()

    def reload(self):
        if not self.busy:
            self.start(self.project.storage_inventory, 'list')

    def completed(self):
        try:
            value, error = self.results.get_nowait()
        except Empty:
            return
        self.timer.stop()
        self.busy = False
        if error:
            self.status.setText('Could not complete cleanup: ' + error)
        elif self.mode == 'list':
            self.rows = value
            previous = self.group.currentText()
            self.group.blockSignals(True)
            self.group.clear()
            self.group.addItem('All platforms and storage')
            self.group.addItems(sorted({row['group'] for row in self.rows}))
            index = self.group.findText(previous)
            self.group.setCurrentIndex(max(0, index))
            self.group.blockSignals(False)
            self.render()
            self.status.setText(str(len(self.rows)) + ' owned outputs. Delete all applies to the displayed category only.')
        else:
            message = str(len(value['removed'])) + ' outputs deleted.'
            if value['skipped']:
                message += '\nKept: ' + '\n'.join(value['skipped'])
            QMessageBox.information(self, 'Cleanup result', message)
            self.reload()
        self.update_buttons()

    def visible_rows(self):
        group = self.group.currentText() if self.group.currentIndex() else None
        return [row for row in self.rows if group is None or row['group'] == group]

    def render(self, *_):
        self.table.clear()
        for row in self.visible_rows():
            item = QTreeWidgetItem([row['group'], row['name'], row['protected'] or 'Can delete', row['path']])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            if row['protected']:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setToolTip(3, row['path'])
            self.table.addTopLevelItem(item)
        for column in range(3):
            self.table.resizeColumnToContents(column)
        self.update_buttons()

    def update_buttons(self):
        self.refresh.setEnabled(not self.busy)
        self.group.setEnabled(not self.busy)
        self.table.setEnabled(not self.busy)
        self.selected.setEnabled(not self.busy and bool(self.table.selectedItems()))
        self.all.setEnabled(not self.busy and any(not row['protected'] for row in self.visible_rows()))
        self.close_buttons.setEnabled(not self.busy)

    def remove(self, all_visible=False):
        if self.busy:
            return
        rows = self.visible_rows() if all_visible else [item.data(0, Qt.ItemDataRole.UserRole)
                                                       for item in self.table.selectedItems()]
        rows = [row for row in rows if not row['protected']]
        if not rows:
            return
        details = '\n'.join(row['path'] for row in rows)
        box = QMessageBox(QMessageBox.Icon.Warning, 'Delete local build outputs?',
                          f'Permanently delete {len(rows)} local outputs? Active and pinned outputs will be checked again.',
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText(details)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        selections = {}
        for row in rows:
            selections.setdefault(row['group'], []).append(row['name'])
        self.start(partial(self.project.delete_storage, selections), 'delete')

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
