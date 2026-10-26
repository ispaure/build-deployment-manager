"""Asynchronous settings editor; project code never runs on the Qt thread."""
from queue import Empty, Queue
from threading import Event
import os

from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .redaction import Redactor


class SettingsTask(QRunnable):
    def __init__(self, action, results):
        super().__init__()
        self.action, self.results = action, results
        self.cancelled = Event()

    def run(self):
        try:
            value = self.action(self.cancelled.is_set)
            self.results.put((value, None))
        except Exception as error:
            self.results.put((None, str(error)))


class SettingsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project, self.controls, self.read_only = project, {}, set()
        self.rows = {}
        self.field_rows, self.forms, self.origins = [], {}, []
        self.setWindowTitle('Project settings')
        self.resize(800, 650)
        layout = QVBoxLayout(self)
        scope = QLabel('Settings for: ' + str(getattr(project, 'root', 'selected project')))
        scope.setWordWrap(True)
        layout.addWidget(scope)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a setting, tool or destination…')
        self.search.setAccessibleName('Search project settings')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_fields)
        self.show_origins = QCheckBox('Show value sources')
        self.show_origins.setToolTip('Show whether a value comes from project defaults, a profile or the environment.')
        self.show_origins.toggled.connect(self.toggle_origins)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.show_origins)
        layout.addLayout(tools)
        self.search_hint = QLabel('No matching settings. Clear the search or try another word.')
        self.search_hint.hide()
        layout.addWidget(self.search_hint)
        factory = getattr(project, 'settings_navigation', None)
        self.navigation = factory(self) if factory else QSplitter(self)
        if factory:
            self.sidebar, self.stack = self.navigation.sidebar, self.navigation.stack
        else:
            self.sidebar, self.stack = QTreeWidget(), QStackedWidget()
            self.sidebar.setHeaderHidden(True)
            self.navigation.addWidget(self.sidebar)
            self.navigation.addWidget(self.stack)
            self.navigation.setStretchFactor(1, 1)
            self.navigation.setSizes([210, 570])
        self.sidebar.setAccessibleName('Settings categories')
        self.sidebar.currentItemChanged.connect(self.select_section)
        layout.addWidget(self.navigation, 1)
        # Hidden navigation must not leave the remaining labels sharing all the
        # dialog height. Keep the access/loading message together at the top.
        self.empty_space = QWidget()
        layout.addWidget(self.empty_space, 1)
        self.empty_space.hide()
        self.help_text = help_text = QLabel('Save changes to the local profile. One-run build overrides belong in the plan. '
                           'Credential fields contain file references, never private-key contents.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.buttons = buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.status = QLabel('Loading project settings…')
        self.status.setWordWrap(True)
        layout.insertWidget(1, self.status)
        self.retry = QPushButton('Retry loading settings')
        self.retry.clicked.connect(self.load)
        retry_actions = QHBoxLayout()
        retry_actions.addWidget(self.retry)
        retry_actions.addStretch()
        layout.addLayout(retry_actions)
        layout.addWidget(buttons)

        self.redact = Redactor(os.environ.get(name) for name in
                              getattr(project, 'secret_environment', ('GH_TOKEN', 'GITHUB_TOKEN', 'FIREBASE_TOKEN')))
        self.results = Queue()
        self.busy, self.dirty, self.saving, self.closed = False, False, False, False
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.completed)
        self.load()

    def start(self, action, saving=False):
        self.busy, self.saving = True, saving
        self.navigation.setVisible(True)
        self.empty_space.hide()
        self.help_text.hide()
        self.navigation.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(not saving)
        self.retry.setVisible(False)
        self.status.setText('Saving settings…' if saving else 'Loading project settings… You can cancel while this loads.')
        self.task = SettingsTask(action, self.results)
        self.timer.start()
        QThreadPool.globalInstance().start(self.task)

    def load(self):
        if self.busy:
            return
        project = self.project
        def action(cancelled):
            loader = getattr(project, 'load_settings', None)
            return loader(cancelled=cancelled) if loader else project.settings_view()
        self.start(action)

    def completed(self):
        try:
            value, error = self.results.get_nowait()
        except Empty:
            return
        self.timer.stop()
        self.busy = False
        if self.closed:
            return
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(True)
        if error is None and not self.saving:
            try:
                self.render(value)
            except Exception as failure:
                error = str(failure)
        if error is not None:
            self.status.setText(('Settings were not saved. ' if self.saving else 'Could not load settings. ') +
                                self.redact(error) + ' Check the project interpreter, then retry.')
            self.retry.setVisible(not self.saving)
            self.navigation.setVisible(bool(self.controls))
            self.empty_space.setVisible(not self.controls)
            self.help_text.setVisible(bool(self.controls))
        elif self.saving:
            self.dirty = False
            self.accept()
            return
        else:
            self.help_text.setVisible(bool(self.controls))
            self.status.setText('Settings loaded. Changes are saved for this checkout. Credential references only.'
                                if self.controls else 'This project exposes no editable settings. Accounts and test machines are managed separately.')
        self.navigation.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(self.controls) and (self.saving or error is None))
        self.saving = False

    def mark_dirty(self, *_):
        self.dirty = True
        self.status.setText('Unsaved changes · Save applies them to this project. Cancel keeps the previous values.')

    def reject(self):
        if self.closed:
            return
        if self.saving and self.busy:
            return
        if self.dirty and QMessageBox.question(self, 'Discard unsaved settings?',
                'Close without saving your changes?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.closed = True
        if hasattr(self, 'task'):
            self.task.cancelled.set()
        self.timer.stop()
        self.field_rows.clear()
        self.forms.clear()
        self.origins.clear()
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.setAccepted(self.closed)

    def render(self, rows):
        if not isinstance(rows, dict):
            raise ValueError('The project returned an invalid settings response.')
        from .credentials import reject_secrets
        reject_secrets(rows)
        for entry in rows.values():
            if not isinstance(entry, dict) or 'value' not in entry:
                raise ValueError('Each settings field must declare a value.')
        self.rows = rows
        self.field_rows, self.origins = [], []
        self.controls.clear()
        self.read_only.clear()
        self.sidebar.clear()
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        forms = {}
        self.forms = forms
        for name, entry in rows.items():
            group = entry.get('section', name.split('.')[0].replace('_', ' ').title())
            if group not in forms:
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                content = QWidget()
                form = QFormLayout(content)
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                scroll.setWidget(content)
                forms[group] = form
                index = self.stack.addWidget(scroll)
                item = QTreeWidgetItem([group])
                from PySide6.QtCore import Qt
                item.setData(0, Qt.ItemDataRole.UserRole, index)
                self.sidebar.addTopLevelItem(item)
            if entry.get('choices'):
                control = QComboBox()
                control.addItems(entry['choices'])
                if control.findText(str(entry['value'])) < 0:
                    control.addItem(str(entry['value']))
                control.setCurrentText(str(entry['value']))
            elif entry.get('kind') == 'multiline':
                control = QPlainTextEdit(str(entry['value']))
                control.setFixedHeight(110)
                control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            elif entry.get('kind') == 'bool':
                control = QCheckBox()
                control.setChecked(bool(entry['value']))
            elif entry.get('kind') == 'int':
                control = QSpinBox()
                control.setRange(entry.get('minimum', -2147483648), entry.get('maximum', 2147483647))
                control.setValue(int(entry['value']))
                control.setSuffix(entry.get('suffix', ''))
            else:
                control = QLineEdit(str(entry['value']))
            label = entry.get('label', name.replace('_', ' ').replace('.', ' · ').capitalize())
            control.setAccessibleName(label)
            description = entry.get('description', label)
            control.setToolTip(description)
            if entry.get('read_only', False):
                self.read_only.add(name)
                if isinstance(control, (QLineEdit, QPlainTextEdit)):
                    control.setReadOnly(True)
                else:
                    control.setEnabled(False)
            self.controls[name] = control
            row = QVBoxLayout()
            input_row = QHBoxLayout()
            input_row.addWidget(control)
            if entry.get('kind') in ('reference', 'protected-file', 'directory'):
                browse = QPushButton('Locate…')
                browse.setToolTip(description)
                browse.setEnabled(not entry.get('read_only', False))
                browse.setProperty('fieldName', name)
                browse.setProperty('fieldKind', entry['kind'])
                browse.clicked.connect(self.locate_field)
                input_row.addWidget(browse)
            row.addLayout(input_row)
            if description != label:
                explanation = QLabel(description)
                explanation.setWordWrap(True)
                row.addWidget(explanation)
            origin = QLabel('Source: ' + entry.get('origin', 'repository default'))
            origin.setWordWrap(True)
            origin.setToolTip(description)
            origin.setVisible(self.show_origins.isChecked())
            self.origins.append(origin)
            row.addWidget(origin)
            heading = QLabel(label)
            heading.setToolTip(description)
            forms[group].addRow(heading, row)
            self.field_rows.append((name, group, heading))
        if self.sidebar.topLevelItemCount():
            self.sidebar.setCurrentItem(self.sidebar.topLevelItem(0))

        for control in self.controls.values():
            signal = (control.toggled if isinstance(control, QCheckBox) else
                      control.valueChanged if isinstance(control, QSpinBox) else
                      control.currentTextChanged if isinstance(control, QComboBox) else control.textChanged)
            signal.connect(self.mark_dirty)
        self.filter_fields()

    def toggle_origins(self, visible):
        for label in self.origins:
            label.setVisible(visible)

    def filter_fields(self, *_):
        query = self.search.text().strip().casefold()
        groups = set()
        for name, group, heading in self.field_rows:
            entry = self.rows[name]
            text = ' '.join((name, group, entry.get('label', ''), entry.get('description', ''))).casefold()
            visible = all(word in text for word in query.split())
            self.forms[group].setRowVisible(heading, visible)
            if visible:
                groups.add(group)
        first = None
        for index in range(self.sidebar.topLevelItemCount()):
            item = self.sidebar.topLevelItem(index)
            item.setHidden(item.text(0) not in groups)
            if not item.isHidden() and first is None:
                first = item
        selected = self.sidebar.currentItem()
        if first is not None and (selected is None or selected.isHidden()):
            self.sidebar.setCurrentItem(first)
        self.stack.setVisible(bool(groups))
        self.search_hint.setVisible(bool(self.rows) and not groups)
        self.toggle_origins(self.show_origins.isChecked())

    def select_section(self, item, previous):
        if item is not None:
            from PySide6.QtCore import Qt
            self.stack.setCurrentIndex(item.data(0, Qt.ItemDataRole.UserRole))

    def locate(self, control, kind):
        if kind == 'directory':
            path = QFileDialog.getExistingDirectory(self, 'Locate tool/runtime directory', control.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Locate existing credential or tool file', control.text())
        if path:
            control.setText(path)

    def locate_field(self):
        button = self.sender()
        self.locate(self.controls[button.property('fieldName')], button.property('fieldKind'))

    def change_version(self):
        value, accepted = QInputDialog.getText(self, 'Change tracked app version',
            'App version (this edits pyproject.toml and requires a commit):')
        if not accepted:
            return
        if QMessageBox.question(self, 'Edit tracked source?', 'Change the source app version to ' + value + '?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.set_app_version(value)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Version not changed', str(error))

    def save(self):
        if self.busy:
            return
        values = {}
        for name, field in self.controls.items():
            if name in self.read_only:
                continue
            if isinstance(field, QCheckBox):
                value = field.isChecked()
            elif isinstance(field, QSpinBox):
                value = field.value()
            elif isinstance(field, QComboBox):
                value = field.currentText()
            elif isinstance(field, QPlainTextEdit):
                value = field.toPlainText()
            else:
                value = field.text()
            values[name] = value
        from .credentials import validate_settings_changes
        try:
            validate_settings_changes(self.rows, values, getattr(self.project, 'root', None))
        except ValueError as error:
            self.status.setText(str(error))
            return
        project = self.project
        def action(cancelled):
            saver = getattr(project, 'store_settings', None)
            return saver(values, cancelled=cancelled) if saver else project.save_settings(values)
        self.start(action, saving=True)
