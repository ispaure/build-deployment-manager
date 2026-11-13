"""Project storage overview, reviewed cleanup and cooperative worker lifetimes."""
from functools import partial
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from queue import Empty, Queue
from threading import Event
from time import perf_counter

from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QTabWidget, QWidget, QFileDialog, QInputDialog, QPlainTextEdit, QHeaderView,
    QToolButton, QProgressBar, QSplitter,
    QSizePolicy,
    QAbstractButton,
)

from .ui_components import style_button, style_dialog_buttons


def size_text(value):
    if value is None:
        return 'Not yet measured'
    from commonUtils.filesystem import format_size
    return format_size(value)


def saved_run_name(path):
    kind = PureWindowsPath if PureWindowsPath(path).is_absolute() else PurePosixPath
    return kind(path).parent.name


def state_text(row):
    reason = row.get('protected') or row.get('protected_descendant') or ''
    if not reason:
        return 'Available to review'
    lowered = reason.lower()
    if 'active' in lowered or 'in use' in lowered:
        return 'In use'
    if 'pin' in lowered or '.keep' in lowered:
        return 'Pinned to keep'
    if any(word in lowered for word in ('hold', 'retained', 'review', 'continuation')):
        return 'Kept for a later run'
    return 'Unavailable'


class EvidenceItem(QTreeWidgetItem):
    """Compatibility item type; bulk sorting happens in the worker model."""


class StorageCategories(QTreeWidget):
    """Make Return activation explicit across native Qt platform styles."""
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem():
            self.itemActivated.emit(self.currentItem(), self.currentColumn())
            event.accept()
            return
        super().keyPressEvent(event)


class StorageTask(QRunnable):
    def __init__(self, action, results, project, generation):
        super().__init__()
        self.action, self.results = action, results
        self.project, self.generation = project, generation
        self.cancelled, self.done = Event(), Event()
        self.progress = (0, 0, '')

    def report(self, done, total, message):
        # Replace progress rather than accumulating one queued event per file.
        self.progress = (done, total, message)

    def publish(self, value):
        if not self.cancelled.is_set():
            self.results.put((self, 'cached', value, None))

    def run(self):
        value = error = None
        try:
            value = self.action(self)
        except Exception as caught:
            error = caught
        finally:
            self.done.set()
            self.results.put((self, 'done', value, error))


class StorageDialog(QDialog):
    _ROW_BATCH_SIZE = 64
    _ROW_SLICE_MS = 5

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.rows = project, []
        self.snapshot = None
        self.results = Queue()
        self.task = None
        self.busy = False
        self.mode = ''
        self.generation = 0
        self.close_requested = self.closed = False
        self.evidence_loaded = False
        self.outputs_loaded = False
        self.workflows_loaded = False
        self._render_jobs = []
        self._render_selection = {}
        self._preview = None
        self.last_outcome = None
        self._mutation = False
        self._project_identity = None
        self.cache = None
        self.setWindowTitle('Manage build storage')
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        self.scope_text = 'Storage for: ' + str(getattr(project, 'root', 'selected checkout'))
        self.scope = QLabel(self.scope_text)
        self.scope.setToolTip(self.scope_text)
        self.scope.setAccessibleName(self.scope_text)
        self.scope.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.scope)
        self.totals = QLabel('Finding project-owned storage…')
        self.totals.setWordWrap(True)
        self.totals.setTextFormat(Qt.TextFormat.PlainText)
        self.totals.setAccessibleName('Accounted storage and measurement status')
        layout.addWidget(self.totals)
        self.category_list = self.tree(['Category', 'Size on disk', 'Available to review'], 'Storage categories', StorageCategories)
        self.category_list.setMaximumHeight(126)
        self.category_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.category_list.setColumnWidth(0, 220)
        self.category_list.setColumnWidth(1, 130)
        self.category_list.itemActivated.connect(self.category_activated)
        self.category_list.itemClicked.connect(self.category_activated)
        layout.addWidget(self.category_list)
        self.category_explanation = QLabel('Builds may need preparing again. Caches can be rebuilt. '
            'Saved runs keep diagnosis and delivery records. Available amounts are estimates, checked again before cleanup.')
        self.category_explanation.setWordWrap(True)
        layout.addWidget(self.category_explanation)
        self.chart_toggle = QToolButton()
        self.chart_toggle.setText('Show space chart')
        self.chart_toggle.setCheckable(True)
        self.chart_toggle.toggled.connect(self.toggle_chart)
        layout.addWidget(self.chart_toggle)
        self.chart = None
        self.chart_holder = QWidget()
        self.chart_holder.setMaximumHeight(200)
        self.chart_layout = QVBoxLayout(self.chart_holder)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_holder.hide()
        layout.addWidget(self.chart_holder)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        outputs = QWidget()
        output_layout = QVBoxLayout(outputs)
        self.tabs.addTab(outputs, 'Builds and files')
        self.group = QComboBox()
        self.group.setAccessibleName('Build storage category')
        self.group.addItem('All build files', None)
        self.group.currentIndexChanged.connect(self.render)
        self.refresh = QPushButton('Refresh storage')
        self.refresh.clicked.connect(self.reload)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.group, 1)
        toolbar.addWidget(style_button(self.refresh))
        output_layout.addLayout(toolbar)
        self.table = self.tree(['Build or working files', 'Size on disk', 'State'], 'Owned build outputs')
        self.table.setColumnWidth(0, 330)
        self.table.setColumnWidth(1, 150)
        output_layout.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.currentItemChanged.connect(lambda row, old: self.show_details(row))
        buttons = QHBoxLayout()
        self.selected = QPushButton('Review cleanup…')
        self.all = QPushButton('Select available shown')
        self.selected.clicked.connect(lambda: self.remove(False))
        self.all.clicked.connect(self.select_available)
        buttons.addWidget(style_button(self.selected))
        buttons.addStretch()
        buttons.addWidget(style_button(self.all))
        output_layout.addLayout(buttons)

        evidence = QWidget()
        evidence_layout = QVBoxLayout(evidence)
        self.evidence_tab = self.tabs.addTab(evidence, 'Saved runs and test results')
        note = QLabel('Remove bulky files to keep run outcomes, reports and receipts. '
                      'Deleting an entire run also removes its local history.')
        note.setWordWrap(True)
        evidence_layout.addWidget(note)
        self.evidence = self.tree(['Run or file', 'Size on disk', 'Bulky files', 'State'], 'Test results and evidence')
        self.evidence.setColumnWidth(0, 280)
        self.evidence.setColumnWidth(1, 130)
        self.evidence.setColumnWidth(2, 130)
        self.evidence.itemSelectionChanged.connect(self.update_buttons)
        self.evidence.currentItemChanged.connect(lambda row, old: self.show_details(row))
        evidence_layout.addWidget(self.evidence, 1)
        actions = QHBoxLayout()
        self.evidence_refresh = QPushButton('Refresh storage')
        self.evidence_files = QPushButton('Remove bulky files…')
        self.evidence_runs = QPushButton('Delete entire runs…')
        self.evidence_refresh.clicked.connect(self.reload)
        self.evidence_files.clicked.connect(lambda: self.remove_evidence(False))
        self.evidence_runs.clicked.connect(lambda: self.remove_evidence(True))
        for button in (self.evidence_files, self.evidence_runs, self.evidence_refresh):
            actions.addWidget(style_button(button))
        evidence_layout.addLayout(actions)

        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        self.advanced_tab = self.tabs.addTab(advanced, 'Advanced')
        workflow_note = QLabel('Retire a superseded workflow to release its storage holds. '
            'It cannot continue afterward; logs, receipts and outcomes remain. '
            'Unknown delivery outcomes still need checking with the provider.')
        workflow_note.setWordWrap(True)
        advanced_layout.addWidget(workflow_note)
        self.workflows = self.tree(['Workflow', 'Operation', 'Outcome', 'Held locations', 'State'], 'Retained workflows')
        for column, width in enumerate((200, 150, 120, 100)):
            self.workflows.setColumnWidth(column, width)
        self.workflows.itemSelectionChanged.connect(self.update_buttons)
        self.workflows.currentItemChanged.connect(lambda row, old: self.show_details(row, workflow=True))
        advanced_layout.addWidget(self.workflows, 1)
        self.retire = QPushButton('Retire selected workflows…')
        self.retire.clicked.connect(self.retire_selected)
        advanced_layout.addWidget(style_button(self.retire))
        from .adapter_sdk import supports
        if supports(project, 'enroll_storage'):
            from .ui_components import WrappingLayout
            adoption = QWidget()
            adoption_layout = WrappingLayout(adoption)
            for name, title, kind in (
                ('adopt_directory', 'Adopt disposable build folder…', 'directory'),
                ('adopt_simulator', 'Adopt disposable simulator…', 'simulator'),
                ('adopt_legacy', 'Adopt legacy build folder…', 'legacy'),
            ):
                button = QPushButton(title)
                button.clicked.connect(partial(self.enroll, kind))
                setattr(self, name, button)
                adoption_layout.addWidget(button)
            advanced_layout.addWidget(adoption)
        self.tabs.currentChanged.connect(self.evidence_tab_changed)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Selected storage details')
        self.details.setPlaceholderText('Select an item to inspect its path, protection and measurement details.')
        self.details.setMaximumHeight(112)
        self.details.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        footer.addWidget(self.progress, 1)
        self.stop = QPushButton('Stop')
        self.stop.clicked.connect(self.cancel)
        footer.addWidget(self.stop)
        self.details_button = QPushButton('Item details…')
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.open_details)
        self.details.textChanged.connect(lambda: self.details_button.setEnabled(bool(self.details.toPlainText())))
        footer.addWidget(self.details_button)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        style_dialog_buttons(self.close_buttons)
        footer.addWidget(self.close_buttons)
        layout.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.completed)
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(0)
        self.render_timer.timeout.connect(self.render_slice)
        self.finished.connect(self._finished)
        for button in self.findChildren(QAbstractButton):
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Initial controls paint before imports, filesystem discovery or row creation.
        self.busy = True
        self.adapt_layout()
        self.update_buttons()
        QTimer.singleShot(0, self.initial_reload)

    def initial_reload(self):
        if self.closed or self.close_requested:
            return
        self.busy = False
        self.reload()

    @staticmethod
    def tree(headers, accessible, tree_type=QTreeWidget):
        tree = tree_type()
        tree.setHeaderLabels(headers)
        tree.setAccessibleName(accessible)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(120)
        tree.setSortingEnabled(False)
        tree.setTabKeyNavigation(False)
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree.header().setStretchLastSection(True)
        return tree

    def start(self, action, mode, *, mutation=False):
        if self.busy or self.close_requested or self.closed:
            return False
        self.generation += 1
        self.mode, self._mutation = mode, mutation
        self.task = StorageTask(action, self.results, self.project, self.generation)
        self.busy = True
        self.status.setText({'list': 'Reading project-owned storage…', 'preview': 'Checking the cleanup selection…',
                             'delete': 'Rechecking cleanup eligibility…', 'retire': 'Retiring selected workflows…',
                             'enroll': 'Adopting the reviewed location…'}[mode])
        self.progress.setRange(0, 0)
        self.update_buttons()
        self.timer.start()
        QThreadPool.globalInstance().start(self.task)
        return True

    def inventory(self, task):
        from .storage_inventory import gather
        from .storage_cleanup import project_identity
        from commonUtils.filesystem.index import DirectoryCache
        if self.cache is None:
            self.cache = DirectoryCache()
        identity = project_identity(task.project)
        def publish(value):
            value = dict(value, project_identity=identity)
            task.publish(value)
        try:
            value = gather(task.project, cache=self.cache, cancelled=task.cancelled.is_set, report=task.report,
                           publish_cached=publish)
        finally:
            self.cache.close()
        if project_identity(task.project) != identity:
            raise ValueError('Project changed during discovery. Reopen storage.')
        return dict(value, project_identity=identity)

    def reload(self):
        if self.busy or self.close_requested or self.closed:
            return
        if self.snapshot:
            self.totals.setText('Refreshing — previously shown sizes are stale estimates.')
            self.details.clear()
        self.start(self.inventory, 'list')

    def completed(self):
        if self.task and not self.close_requested:
            done, total, message = self.task.progress
            if message and not self.task.cancelled.is_set():
                self.status.setText(message)
                self.progress.setRange(0, total if total else 0)
                if total:
                    self.progress.setValue(done)
        for _ in range(8):
            try:
                task, kind, value, error = self.results.get_nowait()
            except Empty:
                break
            if task is not self.task or task.generation != self.generation:
                continue
            if kind == 'cached':
                if not task.cancelled.is_set() and not self.close_requested and task.project is self.project:
                    self.accept_snapshot(value, cached=True)
                continue
            self.task = None
            self.timer.stop()
            self._mutation = False
            if self.close_requested:
                if self.mode in {'delete', 'retire'}:
                    self.last_outcome = value or dict(removed=[], skipped=[], failed=[str(error)] if error else [],
                                                      cancelled=task.cancelled.is_set())
                    self.show_outcome(self.last_outcome)
                self._render_jobs.clear()
                self.render_timer.stop()
                self.busy = False
                QTimer.singleShot(0, self.reject)
                return
            if task.project is not self.project:
                self.snapshot = None
                self._project_identity = None
                self._render_jobs.clear()
                self.render_timer.stop()
                self.table.clear(); self.evidence.clear(); self.workflows.clear()
                self.status.setText('Project changed. Refresh storage before reviewing cleanup.')
            elif self.mode in {'delete', 'retire', 'enroll'}:
                value = value or dict(removed=[], skipped=[], failed=[str(error)] if error else [],
                                     cancelled=task.cancelled.is_set())
                self.last_outcome = value
                self._render_jobs.clear()
                self.render_timer.stop()
                self.busy = False
                if self.mode == 'enroll' and not error:
                    QMessageBox.information(self, 'Storage adopted', 'The reviewed location is now project-owned. Refreshing its inventory.')
                else:
                    self.show_outcome(value)
                self.reload()
                return
            elif task.cancelled.is_set():
                self._render_jobs.clear()
                self.render_timer.stop()
                self.status.setText('Stopped. Shown sizes may be incomplete or stale. Refresh before cleanup.')
                self._project_identity = None
            elif error:
                self.status.setText('Storage request failed: ' + str(error))
                self._project_identity = None
            elif self.mode == 'list':
                self.accept_snapshot(value)
            elif self.mode == 'preview':
                self._preview = value
                self.busy = False
                self.confirm_preview(value)
                return
            self.busy = bool(self._render_jobs)
            self.update_buttons()

    def accept_snapshot(self, value, *, cached=False):
        self.details.clear()
        self.snapshot = value
        self._project_identity = value.get('project_identity')
        self.rows = [row for row in value['rows'] if row['source'] == 'output']
        self.outputs_loaded = self.evidence_loaded = self.workflows_loaded = False
        self.category_list.clear()
        from .storage_inventory import BUILDS, CACHES, SAVED_RUNS
        descriptions = {BUILDS: 'Build preparations, snapshots and workspaces',
                        CACHES: 'Project-described caches; rebuilding takes time',
                        SAVED_RUNS: 'Run records, reports and diagnosis evidence'}
        for category, amounts in value['categories'].items():
            suffix = ' · partial' if amounts['partial'] else ''
            if amounts['stale']:
                suffix += ' · stale'
            elif amounts.get('estimated'):
                suffix += ' · estimate'
            available = size_text(amounts.get('reviewable_bytes', 0)) + ' estimated'
            if amounts.get('reviewable_unknown'):
                available += ' + unknown'
            item = QTreeWidgetItem([category, size_text(amounts['allocated_bytes']) + suffix, available])
            item.setToolTip(0, descriptions.get(category, ''))
            item.setData(0, Qt.ItemDataRole.UserRole, category)
            self.category_list.addTopLevelItem(item)
        qualifiers = []
        if value['partial']:
            qualifiers.append('partial estimate; some sizes are unknown')
        if value['stale'] or cached:
            qualifiers.append('cached or reported estimates; refreshing' if self.task else 'cached or reported estimate')
        elif value.get('estimated'):
            qualifiers.append('reported estimate')
        self.totals.setText(size_text(value['allocated_bytes']) + ' accounted for · Size on disk' +
                            (' · ' + '; '.join(qualifiers) if qualifiers else '') +
                            '. Shared and nested locations counted once. Other locations are outside this inventory.')
        previous = self.group.currentData()
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem('All build files', None)
        for category in (BUILDS, CACHES):
            self.group.addItem(category, category)
        self.group.setCurrentIndex(max(0, self.group.findData(previous)))
        self.group.blockSignals(False)
        self.update_chart()
        self.evidence_tab_changed(self.tabs.currentIndex())
        if not cached:
            issues = value.get('issues', ())
            self.status.setText(f'{len(value["rows"])} storage entries. Select items to review what cleanup would remove.' +
                                (f' {len(issues)} scan issues; inspect item details.' if issues else ''))

    def category_activated(self, item, column=0):
        from .storage_inventory import SAVED_RUNS
        category = item.data(0, Qt.ItemDataRole.UserRole)
        if category == SAVED_RUNS:
            self.tabs.setCurrentIndex(self.evidence_tab)
        else:
            self.tabs.setCurrentIndex(0)
            self.group.setCurrentIndex(max(0, self.group.findData(category)))

    def toggle_chart(self, visible):
        previous_size = self.size()
        if visible and self.chart is None:
            from commonUtils.ui.file_browser.storage import Treemap
            self.chart = Treemap()
            self.chart.setMinimumHeight(100 if self.width() < 800 else 180)
            self.chart.selected.connect(self.chart_selected)
            self.chart_layout.addWidget(self.chart)
            self.update_chart()
        self.chart_toggle.setText('Hide space chart' if visible else 'Show space chart')
        self.adapt_layout()
        self.chart_holder.setVisible(visible)
        self.layout().activate()
        self.resize(previous_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'details_button'):
            self.adapt_layout()

    def adapt_layout(self):
        narrow = self.width() < 800
        self.scope.setText(self.scope.fontMetrics().elidedText(
            self.scope_text, Qt.TextElideMode.ElideMiddle, max(100, self.width() - 40)))
        self.category_list.setMinimumHeight(76)
        self.category_list.setMaximumHeight(90 if narrow else 126)
        # In a narrow window the optional chart replaces the category summary;
        # the full item list, protections and exact Details remain accessible.
        self.category_list.setVisible(not (narrow and self.chart_toggle.isChecked()))
        self.category_explanation.setVisible(not narrow)
        if self.chart is not None:
            self.chart.setMinimumHeight(100 if narrow else 180)
            self.chart_holder.setMaximumHeight(112 if narrow else 200)
        width = max(430, self.width() - 90)
        self.table.setColumnWidth(0, max(140, width - 280) if narrow else 330)
        self.table.setColumnWidth(1, 100 if narrow else 150)
        self.evidence.setColumnWidth(0, max(130, width - 345) if narrow else 280)
        self.evidence.setColumnWidth(1, 90 if narrow else 130)
        self.evidence.setColumnWidth(2, 90 if narrow else 130)

    def open_details(self):
        if not self.details.toPlainText():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Item details')
        dialog.resize(min(700, self.width()), 330)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setAccessibleName('Selected storage details')
        view.setDocument(self.details.document())
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def update_chart(self):
        if self.chart is not None and self.snapshot:
            self.chart.set_items([(Path(category), amount) for category, amount in self.snapshot['chart']])
            self.chart.setAccessibleDescription('Allocated file bytes from the category list. Unknown bytes have no area. Selection only; no deletion.')

    def chart_selected(self, path):
        for index in range(self.category_list.topLevelItemCount()):
            item = self.category_list.topLevelItem(index)
            if item.text(0) == str(path):
                self.category_list.setCurrentItem(item)
                self.category_activated(item)
                break

    def visible_rows(self):
        category = self.group.currentData()
        return [row for row in self.rows if category is None or row['category'] == category]

    def queue_render(self, tree, rows, kind):
        if tree.isVisible():
            self.details.clear()
        selected = {item.data(0, Qt.ItemDataRole.UserRole).get('key', item.data(0, Qt.ItemDataRole.UserRole).get('path'))
                    for item in tree.selectedItems()}
        for job in self._render_jobs:
            if job['tree'] is tree:
                selected.update(job['selected'])
        self._render_jobs = [job for job in self._render_jobs if job['tree'] is not tree]
        self._render_jobs.append(dict(tree=tree, rows=iter(rows), kind=kind, selected=selected, clearing=True))
        self.busy = True
        self.render_timer.start()
        self.update_buttons()

    def render(self, *_):
        if self.snapshot and not self.close_requested:
            self.outputs_loaded = True
            self.queue_render(self.table, self.visible_rows(), 'output')

    def render_slice(self):
        if self.closed or self.close_requested:
            self._render_jobs.clear()
        start = perf_counter()
        count = 0
        while self._render_jobs and count < self._ROW_BATCH_SIZE and (perf_counter() - start) * 1000 < self._ROW_SLICE_MS:
            job = self._render_jobs[0]
            if job['clearing']:
                if job['tree'].topLevelItemCount():
                    item = job['tree'].takeTopLevelItem(job['tree'].topLevelItemCount() - 1)
                    del item
                    count += 1
                    continue
                job['clearing'] = False
            try:
                row = next(job['rows'])
            except StopIteration:
                self._render_jobs.pop(0)
                selected = job['tree'].selectedItems()
                if selected:
                    job['tree'].setCurrentItem(selected[0])
                continue
            kind = job['kind']
            if kind == 'workflow':
                values = [saved_run_name(row['path']), row.get('operation', ''), row['status'],
                          str(row['holds']), 'Retired' if row.get('retired') else 'Retained']
            else:
                size = size_text(row.get('allocated_bytes'))
                if row.get('partial'):
                    size += ' (partial)'
                elif row.get('stale') or row.get('measurement') == 'reported':
                    size += ' (estimate)'
                values = ([row['label'], size, state_text(row)] if kind == 'output' else
                          [row['label'], size, size_text(row.get('bulky_bytes')), state_text(row)])
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            item.setToolTip(0, row['path'])
            if kind == 'workflow' and (row['status'] in {'running', 'queued'} or row.get('retired') and not row['holds']):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            job['tree'].addTopLevelItem(item)
            if row.get('key', row.get('path')) in job['selected']:
                job['tree'].blockSignals(True)
                item.setSelected(True)
                job['tree'].blockSignals(False)
            count += 1
        if not self._render_jobs:
            self.render_timer.stop()
            self.busy = self.task is not None
            self.sync_details()
            if self.close_requested and not self.busy:
                QTimer.singleShot(0, self.reject)
            self.update_buttons()

    def evidence_tab_changed(self, index):
        self.details.clear()
        if not self.snapshot or self.close_requested:
            return
        if index == 0 and not self.outputs_loaded:
            self.render()
        elif index == self.evidence_tab and not self.evidence_loaded:
            self.evidence_loaded = True
            self.queue_render(self.evidence, [row for row in self.snapshot['rows'] if row['source'] == 'evidence'], 'evidence')
        elif index == self.advanced_tab and not self.workflows_loaded:
            self.workflows_loaded = True
            self.queue_render(self.workflows, self.snapshot['workflows'], 'workflow')
        if not self.busy:
            self.sync_details()

    def load_evidence(self):
        self.reload()

    def show_details(self, item, workflow=False):
        if item is None:
            self.details.clear()
            return
        row = item.data(0, Qt.ItemDataRole.UserRole)
        if not row:
            return
        if not workflow and (not self.snapshot or self.snapshot['by_key'].get(row['key']) != row):
            self.details.clear()
            return
        if workflow:
            text = f"{saved_run_name(row['path'])}\n{row['path']}\nOutcome: {row['status']}\nRetirement keeps evidence and disables continuation."
        else:
            amount = row.get('allocated_bytes')
            text = (f"{row['label']}\n{row['path']}\n{row.get('group', '')}\n"
                    f"{state_text(row)}: {row.get('protected') or row.get('protected_descendant') or 'Live ownership and protections are checked again before removal.'}\n"
                    f"Allocated file bytes: {amount if amount is not None else 'unknown'}; "
                    f"logical file bytes: {row.get('logical_bytes') if row.get('logical_bytes') is not None else 'unknown'}. "
                    f"Category contribution after nested entries: {row.get('accounted_bytes') if row.get('accounted_bytes') is not None else 'unknown'} bytes. "
                    f"Measurement: {row.get('measurement', 'unknown')}; "
                    f"{'stale' if row.get('stale') else 'current at scan'}; {'partial' if row.get('partial') else 'complete'}.\n"
                    'Sizes use 1024-byte units and estimate file allocations, not guaranteed space reclaimed. Links outside owned roots are excluded.')
            if row.get('shared'):
                text += '\nDeclared by: ' + '; '.join(source + ' / ' + str(owner.get('group') or owner.get('kind') or '')
                                                     for source, owner in row['owners'])
            if row.get('scan_issue'):
                text += '\nScan issue: ' + row['scan_issue']
        if self.busy:
            text = 'Storage view updating; this item is not ready for cleanup.\n' + text
        self.details.setPlainText(text)

    def sync_details(self):
        index = self.tabs.currentIndex()
        tree = self.evidence if index == self.evidence_tab else self.workflows if index == self.advanced_tab else self.table
        item = tree.currentItem()
        if item and item.isSelected():
            self.show_details(item, workflow=tree is self.workflows)
        else:
            self.details.clear()

    def selected_rows(self, tree):
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in tree.selectedItems()]

    def selected_evidence(self, *, entire):
        from .storage_cleanup import unavailable
        action = 'runs' if entire else 'bulky'
        return [row for row in self.selected_rows(self.evidence) if not unavailable(row, action)]

    def update_buttons(self):
        if not hasattr(self, 'close_buttons'):
            return
        from .storage_cleanup import unavailable
        ready = not self.busy and not self.close_requested and bool(self._project_identity)
        for button in (self.refresh, self.evidence_refresh):
            button.setEnabled(not self.busy and not self.close_requested)
        self.selected.setEnabled(ready and any(not unavailable(row, 'outputs') for row in self.selected_rows(self.table)))
        self.all.setEnabled(ready and bool(self.rows))
        self.evidence_files.setEnabled(ready and bool(self.selected_evidence(entire=False)))
        self.evidence_runs.setEnabled(ready and bool(self.selected_evidence(entire=True)))
        self.retire.setEnabled(ready and bool(self.workflows.selectedItems()))
        for name in ('adopt_directory', 'adopt_simulator', 'adopt_legacy'):
            if hasattr(self, name):
                getattr(self, name).setEnabled(ready)
        self.stop.setEnabled(self.busy and not self.close_requested)
        if not self.busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    def select_available(self):
        from .storage_cleanup import unavailable
        self.table.blockSignals(True)
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setSelected(not unavailable(item.data(0, Qt.ItemDataRole.UserRole), 'outputs'))
        self.table.blockSignals(False)
        self.update_buttons()

    def remove(self, all_visible=False):
        if all_visible:
            self.select_available()
            return
        self.begin_preview(self.selected_rows(self.table), 'outputs')

    def remove_evidence(self, entire):
        self.begin_preview(self.selected_rows(self.evidence), 'runs' if entire else 'bulky')

    def begin_preview(self, rows, action):
        if self.busy or not rows or not self._project_identity:
            return
        from .storage_cleanup import prepare_preview
        project = self.project
        self.start(lambda task: prepare_preview(project, rows, action,
                    cancelled=task.cancelled.is_set, report=task.report), 'preview')

    def confirm_preview(self, preview):
        if self.close_requested or self.closed:
            return
        if not preview.rows:
            self.status.setText('Nothing is available to remove. ' + '\n'.join(preview.skipped))
            self.update_buttons()
            return
        estimate = size_text(preview.estimated_bytes) + ' estimated'
        box = QMessageBox(QMessageBox.Icon.Warning, 'Review cleanup',
                          f'Remove {len(preview.rows)} selected entries? {estimate}.\n'
                          f'Measurement: {preview.measurement_summary}.\n\n' + preview.consequence,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(
            {'outputs': 'Delete reviewed files', 'bulky': 'Remove bulky files', 'runs': 'Delete entire runs'}[preview.action])
        details = []
        for row in preview.rows:
            amount = row['action'].get('bulky_bytes') if preview.action == 'bulky' else row.get('allocated_bytes')
            stamp = row.get('scanned_at')
            when = datetime.fromtimestamp(stamp).strftime('%Y-%m-%d %H:%M:%S') if stamp else 'project inventory'
            details.append(f"{row['label']}\n{row['path']}\nSize on disk: {size_text(amount)} "
                           f"({amount if amount is not None else 'unknown'} allocated bytes). "
                           f"Measurement: {row.get('measurement', 'unknown')}, {when}.")
        box.setDetailedText('\n\n'.join(details) +
                            ('\n\nKept:\n' + '\n'.join(preview.skipped) if preview.skipped else ''))
        if box.exec() == QMessageBox.StandardButton.Yes and not self.close_requested:
            from .storage_cleanup import execute
            project = self.project
            cache = self.cache
            def remove(task):
                try:
                    return execute(project, preview, cancelled=task.cancelled.is_set, report=task.report)
                finally:
                    if cache:
                        for row in preview.rows:
                            cache.invalidate(Path(row['path']))
            self.start(remove, 'delete', mutation=True)
        else:
            self.status.setText('Cleanup cancelled. No files were removed.')
            self.update_buttons()

    def show_outcome(self, result):
        count = len(result.get('retired', result.get('removed', ())))
        title = 'Workflow retirement' if 'retired' in result else 'Cleanup result'
        message = f'{count} entries ' + ('retired; evidence kept.' if 'retired' in result else 'removed.')
        if result.get('cancelled'):
            message += ' Stopped before starting further items.'
        for key, label in (('skipped', 'Skipped or incomplete'), ('failed', 'Failed')):
            if result.get(key):
                message += '\n' + label + ':\n' + '\n'.join(result[key])
        if result.get('skipped') or result.get('failed'):
            message += '\nAn incomplete removal may have removed some files. Refreshing the inventory before another review.'
        QMessageBox.information(self, title, message)

    def retire_selected(self):
        if self.busy or not self._project_identity:
            return
        rows = self.selected_rows(self.workflows)
        if not rows:
            return
        from .storage_cleanup import CONSEQUENCES, retire
        box = QMessageBox(QMessageBox.Icon.Warning, 'Retire superseded workflows?',
                          f'Retire {len(rows)} workflows? ' + CONSEQUENCES['retire'],
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText('\n'.join(row['path'] for row in rows))
        if box.exec() == QMessageBox.StandardButton.Yes:
            project, identity = self.project, self._project_identity
            self.start(lambda task: retire(project, rows, expected_project=identity,
                       cancelled=task.cancelled.is_set, report=task.report), 'retire', mutation=True)

    def enroll(self, kind, *_):
        if self.busy or not self._project_identity:
            return
        if kind in {'directory', 'legacy'}:
            location = QFileDialog.getExistingDirectory(self, 'Choose a disposable temporary build folder')
        else:
            location, accepted = QInputDialog.getText(self, 'Adopt disposable simulator',
                'Enter the exact UUID of a disposable QA simulator:')
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
            project = self.project
            self.start(lambda task: project.enroll_storage(kind, location), 'enroll', mutation=True)

    def cancel(self):
        if self.task:
            self.task.cancelled.set()
            self.status.setText('Stopping after the current item finishes…' if self._mutation else 'Stopping storage work…')
        else:
            self._render_jobs.clear()
            self.render_timer.stop()
            self.busy = False
            self._project_identity = None
            self.status.setText('Stopped displaying results. Refresh before cleanup.')
        self.update_buttons()

    def _request_close(self):
        if not self.busy:
            return True
        if self.close_requested:
            return False
        if self._mutation:
            answer = QMessageBox.question(self, 'Stop cleanup and close?',
                'The current item must finish. Stop before further items and close when it is safe?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.close_requested = True
        self.cancel()
        if not self.task:
            self.busy = False
            return True
        return False

    def reject(self):
        if self._request_close():
            super().reject()

    def closeEvent(self, event):
        if self._request_close():
            super().closeEvent(event)
        else:
            event.ignore()

    def _finished(self, *_):
        self.closed = True
        self.timer.stop()
        self.render_timer.stop()
