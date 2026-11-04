"""Review and remove project-owned outputs without blocking the GUI on disk I/O."""
from functools import partial
from pathlib import PurePosixPath, PureWindowsPath
from queue import Empty, Queue

from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QTabWidget, QWidget, QFileDialog, QInputDialog,
)

from .ui_components import style_button, style_dialog_buttons


def size_text(value):
    if value is None:
        return 'Unavailable'
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


def saved_run_name(path):
    kind = PureWindowsPath if PureWindowsPath(path).is_absolute() else PurePosixPath
    return kind(path).parent.name


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
        self.setWindowTitle('Project storage and cleanup')
        self.resize(1100, 680)
        layout = QVBoxLayout(self)
        scope = QLabel('Storage for: ' + str(getattr(project, 'root', 'selected checkout')))
        scope.setWordWrap(True)
        layout.addWidget(scope)
        note = QLabel('Manager-owned outputs only. Active, pinned and review-held data is protected. '
                      'Deleting local files does not remove published releases.')
        note.setToolTip('Tools, signing files, credentials, build counters and installed apps are kept. '
                        'Retention and ownership rules are supplied by the project.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        outputs = QWidget()
        output_layout = QVBoxLayout(outputs)
        self.tabs.addTab(outputs, 'Build outputs and caches')
        self.group = QComboBox()
        self.group.addItem('All platforms and storage')
        self.group.currentIndexChanged.connect(self.render)
        output_layout.addWidget(self.group)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Platform / storage', 'Build / snapshot', 'Size', 'Protection', 'Location'])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAccessibleName('Owned build outputs')
        self.table.itemSelectionChanged.connect(self.update_buttons)
        output_layout.addWidget(self.table, 1)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        output_layout.insertWidget(0, self.totals)
        buttons = QHBoxLayout()
        self.refresh = QPushButton('Refresh')
        self.selected = QPushButton('Delete selected…')
        self.all = QPushButton('Delete all unprotected…')
        self.refresh.clicked.connect(self.reload)
        self.selected.clicked.connect(lambda: self.remove(False))
        self.all.clicked.connect(lambda: self.remove(True))
        for button in (self.selected,):
            buttons.addWidget(style_button(button))
        buttons.addStretch()
        buttons.addWidget(QLabel('Bulk cleanup'))
        buttons.addWidget(style_button(self.all))
        toolbar = QHBoxLayout()
        output_layout.removeWidget(self.group)
        toolbar.addWidget(self.group, 1)
        toolbar.addWidget(style_button(self.refresh))
        output_layout.insertLayout(1, toolbar)
        output_layout.addLayout(buttons)
        from .adapter_sdk import supports
        if supports(project, 'enroll_storage'):
            from .ui_components import WrappingLayout
            from .review_ui import Disclosure
            adoption_content = QWidget()
            adoption = WrappingLayout(adoption_content)
            self.adopt_directory = QPushButton('Adopt disposable build folder…')
            self.adopt_simulator = QPushButton('Adopt disposable simulator…')
            self.adopt_legacy = QPushButton('Adopt legacy build folder…')
            self.adopt_directory.clicked.connect(lambda: self.enroll('directory'))
            self.adopt_simulator.clicked.connect(lambda: self.enroll('simulator'))
            self.adopt_legacy.clicked.connect(lambda: self.enroll('legacy'))
            adoption.addWidget(self.adopt_directory)
            adoption.addWidget(self.adopt_simulator)
            adoption.addWidget(self.adopt_legacy)
            output_layout.addWidget(Disclosure('Advanced storage ownership', adoption_content))
        workflows = QWidget()
        workflow_layout = QVBoxLayout(workflows)
        self.tabs.addTab(workflows, 'Retained workflows')
        workflow_note = QLabel('Retire superseded workflows to release their storage holds. '
            'Their logs, receipts and recorded outcomes remain; retired workflows cannot continue. '
            'An unknown outcome still requires checking the provider before starting a replacement delivery.')
        workflow_note.setWordWrap(True)
        workflow_layout.addWidget(workflow_note)
        self.workflows = QTreeWidget()
        self.workflows.setHeaderLabels(['Workflow', 'Operation', 'Outcome', 'Held locations', 'State'])
        self.workflows.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.workflows.itemSelectionChanged.connect(self.update_buttons)
        workflow_layout.addWidget(self.workflows, 1)
        self.retire = QPushButton('Retire selected workflows…')
        self.retire.clicked.connect(self.retire_selected)
        workflow_layout.addWidget(self.retire)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        style_dialog_buttons(self.close_buttons)
        layout.addWidget(self.close_buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.completed)
        self.reload()

    def start(self, action, mode):
        self.busy, self.mode = True, mode
        self.update_buttons()
        self.status.setText({'list': 'Reading owned outputs…', 'delete': 'Deleting reviewed outputs…',
            'retire': 'Retiring selected workflows…', 'enroll': 'Adopting selected disposable storage…'}[mode])
        QThreadPool.globalInstance().start(StorageTask(action, self.results))
        self.timer.start()

    def reload(self):
        if not self.busy:
            self.start(self.inventory, 'list')

    def inventory(self):
        from .adapter_sdk import supports
        from .run_retirement import list_held_or_retired_runs
        entries = self.project.storage_inventory() if supports(self.project, 'storage_inventory') else []
        directory = getattr(self.project, 'results_directory', None)
        runs = list_held_or_retired_runs(directory) if directory else []
        return dict(entries=entries, workflows=runs)

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
            self.rows = value['entries']
            self.workflows.clear()
            for row in value['workflows']:
                item = QTreeWidgetItem([saved_run_name(row['path']), row.get('operation', ''), row['status'],
                    str(row['holds']), 'Retired' if row.get('retired') else 'Retained'])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                item.setToolTip(0, row['path'])
                if row['status'] in {'running', 'queued'} or row.get('retired') and not row['holds']:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.workflows.addTopLevelItem(item)
            for column in range(4):
                self.workflows.resizeColumnToContents(column)
            previous = self.group.currentText()
            self.group.blockSignals(True)
            self.group.clear()
            self.group.addItem('All platforms and storage')
            self.group.addItems(sorted({row.get('category', row['group']) for row in self.rows}))
            index = self.group.findText(previous)
            self.group.setCurrentIndex(max(0, index))
            self.group.blockSignals(False)
            self.render()
            self.status.setText(str(len(self.rows)) + ' owned outputs. Delete all applies to the displayed category only.')
        elif self.mode == 'retire':
            message = str(len(value['retired'])) + ' workflows retired; evidence and outcomes retained.'
            if value['skipped']:
                message += '\nKept: ' + '\n'.join(value['skipped'])
            QMessageBox.information(self, 'Workflow retirement', message)
            self.reload()
        elif self.mode == 'enroll':
            QMessageBox.information(self, 'Disposable storage adopted',
                'The selected location is now owned by project cleanup. Automatic retention: '
                + str(value['retention_days']) + ' days. Review it in the inventory before manual deletion.')
            self.reload()
        else:
            message = str(len(value['removed'])) + ' outputs deleted.'
            if value['skipped']:
                message += '\nKept: ' + '\n'.join(value['skipped'])
            QMessageBox.information(self, 'Cleanup result', message)
            self.reload()
        self.update_buttons()

    def visible_rows(self):
        group = self.group.currentText() if self.group.currentIndex() else None
        return [row for row in self.rows if group is None or row.get('category', row['group']) == group]

    def render(self, *_):
        self.table.clear()
        for row in self.visible_rows():
            item = QTreeWidgetItem([row.get('category', row['group']), row.get('label', row['name']), size_text(row.get('allocated_bytes')),
                                   row['protected'] or 'Can delete', row['path']])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            item.setToolTip(4, row['path'])
            item.setToolTip(3, row['protected'] or 'Can delete')
            self.table.addTopLevelItem(item)
        for column in range(4):
            self.table.resizeColumnToContents(column)
            self.table.setColumnWidth(column, min(self.table.columnWidth(column), (260, 220, 110, 340)[column]))
        rows = self.visible_rows()
        # Adapter groups may include both an owned tree and its cache children.
        # Count each allocation once in the overview.
        from pathlib import Path
        paths = {Path(row['path']) for row in rows}
        unique = [row for row in rows if not any(parent in paths for parent in Path(row['path']).parents)]
        total = sum(row.get('allocated_bytes') or 0 for row in unique)
        deletable_paths = {Path(row['path']) for row in rows if not row['protected']}
        deletable = sum(row.get('allocated_bytes') or 0 for row in rows if not row['protected']
            and not any(parent in deletable_paths for parent in Path(row['path']).parents))
        protected = max(0, total - deletable)
        self.totals.setText(f'{size_text(total)} shown · {size_text(protected)} protected. '
            'Protected storage can exceed automatic budgets. Select a cache category to inspect rebuildable storage. '
            'Shared tools, personal devices and undeclared folders are outside this inventory.')
        self.update_buttons()

    def update_buttons(self):
        self.refresh.setEnabled(not self.busy)
        self.group.setEnabled(not self.busy)
        self.table.setEnabled(not self.busy)
        self.workflows.setEnabled(not self.busy)
        self.retire.setEnabled(not self.busy and bool(self.workflows.selectedItems()))
        if hasattr(self, 'adopt_directory'):
            self.adopt_directory.setEnabled(not self.busy)
            self.adopt_simulator.setEnabled(not self.busy)
            self.adopt_legacy.setEnabled(not self.busy)
        selected = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.table.selectedItems()]
        deletable = [row for row in selected if not row['protected']]
        self.selected.setText(f'Delete {len(deletable)} selected output' + ('s…' if len(deletable) != 1 else '…'))
        self.retire.setText(f'Retire {len(self.workflows.selectedItems())} selected workflow' +
                            ('s…' if len(self.workflows.selectedItems()) != 1 else '…'))
        category = self.group.currentText() if self.group.currentIndex() > 0 else 'all categories'
        self.all.setText('Delete unprotected in ' + category + '…')
        self.selected.setEnabled(not self.busy and bool(deletable))
        self.all.setEnabled(not self.busy and any(not row['protected'] for row in self.visible_rows()))
        self.close_buttons.setEnabled(not self.busy)

    def remove(self, all_visible=False):
        if self.busy:
            return
        rows = self.visible_rows() if all_visible else [item.data(0, Qt.ItemDataRole.UserRole)
                                                       for item in self.table.selectedItems()]
        rows = [row for row in rows if not row['protected']]
        from pathlib import Path
        selected_paths = {Path(row['path']) for row in rows}
        rows = [row for row in rows if not any(parent in selected_paths for parent in Path(row['path']).parents)]
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

    def retire_selected(self):
        if self.busy:
            return
        rows = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.workflows.selectedItems()]
        if not rows:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, 'Retire superseded workflows?',
            f'Retire {len(rows)} workflows and release their storage holds? They cannot continue afterward. '
            'Logs, receipts and unknown external outcomes are preserved. Other workflows and .keep pins remain protected.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText('\n'.join(row['path'] for row in rows))
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        def retire():
            from pathlib import Path
            from .run_retirement import retire_run
            result = dict(retired=[], skipped=[])
            for row in rows:
                try:
                    result['retired'].append(retire_run(self.project.results_directory, Path(row['path']).parent.name, confirmed=True))
                except (OSError, ValueError, RuntimeError) as error:
                    result['skipped'].append(row['path'] + ': ' + str(error))
            return result
        self.start(retire, 'retire')

    def enroll(self, kind):
        if self.busy:
            return
        if kind in {'directory', 'legacy'}:
            location = QFileDialog.getExistingDirectory(self, 'Choose a disposable temporary build folder')
        else:
            location, accepted = QInputDialog.getText(self, 'Adopt disposable simulator',
                'Enter the exact UUID of a QA simulator you want project cleanup to own:')
            if not accepted:
                return
        if not location:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, 'Adopt disposable storage?',
            'Project cleanup will be allowed to delete this location and its data. '
            'Choose only disposable build or QA state.\n\n' + location,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.start(partial(self.project.enroll_storage, kind, location), 'enroll')

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
