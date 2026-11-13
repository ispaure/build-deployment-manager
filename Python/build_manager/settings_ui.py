"""Asynchronous settings editor; project code never runs on the Qt thread."""
from pathlib import Path
from queue import Empty, Queue
from threading import Event
import os

from PySide6.QtCore import QRunnable, QSignalBlocker, QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .redaction import Redactor
from .providers import DELIVERY_LABELS, setting_help
from .settings import setting_reset, validate_settings_resets
from .ui_components import style_button, style_dialog_buttons, search_shortcut, HeadingLabel, style_utilities


RUN_DEFAULTS = ('Run defaults',)
DELIVERY = ('Delivery',)
ENVIRONMENTS = 'Environments & tools'
BUILDS = 'Builds & signing'
ADVANCED = 'Advanced'
INTENTS = ('Run defaults', ENVIRONMENTS, BUILDS, 'Delivery', ADVANCED)
SETTING_SECTIONS = {
    'tools': (ENVIRONMENTS, 'Tools and runtimes'), 'ios': (ENVIRONMENTS, 'iOS simulators'),
    'android': (ENVIRONMENTS, 'Android emulator'), 'vm': (ENVIRONMENTS, 'Virtual machines'),
    'host': (ENVIRONMENTS, 'Host capabilities'), 'testing': (ENVIRONMENTS, 'Test environments'),
    'app': (BUILDS, 'App version'), 'build': (BUILDS, 'Build numbers'), 'signing': (BUILDS, 'Apple signing'),
    'auth': (*DELIVERY, 'Account references'),
    'distribution': (*DELIVERY, 'Store publication'),
    'project': (ADVANCED, 'Project identity'), 'config': (ADVANCED, 'Local settings'),
    'storage': (ADVANCED, 'Storage settings'),
}


def setting_section(name, entry, run_fields):
    if name in run_fields or entry.get('section') in ('Defaults for new runs', 'Run defaults'):
        return RUN_DEFAULTS
    prefix, separator, _ = name.partition('.')
    if separator and prefix in DELIVERY_LABELS:
        return (*DELIVERY, DELIVERY_LABELS[prefix])
    if separator and prefix in SETTING_SECTIONS:
        return SETTING_SECTIONS[prefix]
    return (entry.get('section', prefix.replace('_', ' ').title()),)


def control_value(control):
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QSpinBox):
        return control.value()
    if isinstance(control, QComboBox):
        return control.currentText()
    if isinstance(control, QPlainTextEdit):
        return control.toPlainText()
    return control.text()


def set_control_value(control, value):
    with QSignalBlocker(control):
        if isinstance(control, QCheckBox):
            control.setChecked(value)
        elif isinstance(control, QSpinBox):
            control.setValue(value)
        elif isinstance(control, QComboBox):
            value = str(value)
            if control.findText(value) < 0:
                control.addItem(value)
            control.setCurrentText(value)
        elif isinstance(control, QPlainTextEdit):
            control.setPlainText(str(value))
        else:
            control.setText(str(value))


def plain_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


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
        self.field_rows, self.forms, self.origins = {}, {}, []
        self.sections, self.page_resets, self.reset_buttons = {}, {}, {}
        self.initial_values, self.edits, self.resets = {}, {}, {}
        self.origin_labels = {}
        self.setWindowTitle('Project settings')
        self.resize(800, 650)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        scope = QLabel('Settings for: ' + str(getattr(project, 'root', 'selected project')))
        scope.setWordWrap(True)
        layout.addWidget(scope)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a setting, tool or destination…')
        self.search.setAccessibleName('Search project settings')
        self.search.setClearButtonEnabled(True)
        self.find = search_shortcut(self, self.search)
        self.search.textChanged.connect(self.filter_fields)
        self.show_origins = QCheckBox('Show value sources')
        self.show_origins.setChecked(True)
        self.show_origins.setToolTip('Show where the project obtained each value.')
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
        self.sidebar.setMinimumWidth(170)
        self.sidebar.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sidebar.currentItemChanged.connect(self.select_section)
        layout.addWidget(self.navigation, 1)
        # Hidden navigation must not leave the remaining labels sharing all the
        # dialog height. Keep the access/loading message together at the top.
        self.empty_space = QWidget()
        layout.addWidget(self.empty_space, 1)
        self.empty_space.hide()
        self.help_text = plain_label('More opens Accounts, Test machines, App settings and Manage build storage.')
        layout.addWidget(self.help_text)
        self.buttons = buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.status = plain_label('Loading project settings…')
        layout.insertWidget(1, self.status)
        self.retry = style_button(QPushButton('Retry loading settings'), 'primary')
        self.retry.clicked.connect(self.load)
        retry_actions = QHBoxLayout()
        retry_actions.addWidget(self.retry)
        retry_actions.addStretch()
        layout.addLayout(retry_actions)
        style_dialog_buttons(buttons)
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
            self.status.setText('Changes here apply to this checkout. Use Overrides in Choose work for a single run.'
                                if self.controls.keys() - self.read_only else 'This project exposes no editable settings.')
        self.navigation.setEnabled(True)
        self.saving = False
        self.update_save()

    def update_save(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(self.dirty and not self.busy)

    def update_draft(self):
        self.dirty = bool(self.edits or self.resets)
        if self.resets:
            self.status.setText('Unsaved changes. Save clears the selected checkout overrides and applies your edits.')
        elif self.dirty:
            self.status.setText('Unsaved changes. Save applies them to this checkout.')
        else:
            self.status.setText('Changes here apply to this checkout. Use Overrides in Choose work for a single run.')
        self.update_save()
        self.filter_fields()

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
        if any(not isinstance(entry, dict) or 'value' not in entry for entry in rows.values()):
            raise ValueError('Each settings field must declare a value.')
        self.rows = rows
        self.sidebar.clear()
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.controls.clear()
        self.read_only.clear()
        self.field_rows.clear()
        self.forms.clear()
        self.origins.clear()
        self.origin_labels.clear()
        self.sections.clear()
        self.page_resets.clear()
        self.reset_buttons.clear()
        self.initial_values.clear()
        self.edits.clear()
        self.resets.clear()

        run_fields = {field['id'] for field in getattr(self.project, 'run_fields', ())}
        groups = {}
        for name, entry in rows.items():
            group = setting_section(name, entry, run_fields)
            groups.setdefault(group, []).append(name)

        def order(group):
            return INTENTS.index(group[0]) if group[0] in INTENTS else len(INTENTS)

        for group in sorted(groups, key=order):
            if len(group) > 1 and group[:1] not in self.sections:
                self.add_section(group[:1], groups.get(group[:1], ()))
            if group not in self.sections:
                self.add_section(group, groups[group])
        self.add_section_links(groups)
        self.sidebar.expandAll()
        self.filter_fields()
        style_utilities(self)

    def add_section(self, group, names):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(HeadingLabel(group[-1], section=True))
        links = QVBoxLayout()
        layout.addLayout(links)
        scroll.setWidget(content)
        index = self.stack.addWidget(scroll)
        item = QTreeWidgetItem([group[-1]])
        item.setData(0, Qt.ItemDataRole.UserRole, index)
        item.setToolTip(0, ' → '.join(group))
        if len(group) == 1:
            self.sidebar.addTopLevelItem(item)
        else:
            self.sections[group[:-1]][0].addChild(item)
        self.sections[group] = item, links

        if len([name for name in names if setting_reset(name, self.rows[name])]) > 1:
            reset = QPushButton('Reset page…')
            reset.setAccessibleName('Reset ' + ' → '.join(group))
            reset.setToolTip('Clear supported checkout overrides on this page.')
            reset.clicked.connect(lambda: self.reset_page(group))
            layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
            self.page_resets[group] = reset

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        self.forms[group] = form
        for name in names:
            self.add_field(name, group, form)

    def add_section_links(self, groups):
        for group, (_, links) in self.sections.items():
            for child in self.sections:
                if len(child) == len(group) + 1 and child[:-1] == group:
                    self.add_section_link(links, child[-1], child)

        if RUN_DEFAULTS not in groups:
            return
        _, run_links = self.sections[RUN_DEFAULTS]
        for provider, label in DELIVERY_LABELS.items():
            page = (*DELIVERY, label)
            if page in groups and any(name.startswith(provider + '.') for name in groups[RUN_DEFAULTS]):
                _, links = self.sections[page]
                self.add_section_link(links, 'Open ' + label + ' run defaults', RUN_DEFAULTS)
                self.add_section_link(run_links, 'Open ' + label + ' delivery settings', page)

    def add_section_link(self, layout, label, group):
        button = QPushButton(label)
        button.clicked.connect(lambda: self.open_section(group))
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)

    def open_section(self, group):
        self.search.clear()
        item, _ = self.sections[group]
        self.sidebar.setCurrentItem(item)
        self.sidebar.scrollToItem(item)
        self.sidebar.setFocus()

    def add_field(self, name, group, form):
        entry = self.rows[name]
        if entry.get('choices'):
            control = QComboBox()
            control.addItems(entry['choices'])
            signal = control.currentTextChanged
        elif entry.get('kind') == 'multiline':
            control = QPlainTextEdit()
            control.setTabChangesFocus(True)
            control.setMinimumHeight(self.fontMetrics().height() * 4 + 16)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            signal = control.textChanged
        elif entry.get('kind') == 'bool':
            control = QCheckBox()
            signal = control.toggled
        elif entry.get('kind') == 'int':
            control = QSpinBox()
            control.setRange(entry.get('minimum', -2147483648), entry.get('maximum', 2147483647))
            control.setSuffix(entry.get('suffix', ''))
            signal = control.valueChanged
        else:
            control = QLineEdit()
            signal = control.textChanged
        set_control_value(control, entry['value'])
        self.initial_values[name] = control_value(control)

        default_label = name.replace('_', ' ').replace('.', ' · ').capitalize()
        label = entry.get('label', default_label)
        if group == RUN_DEFAULTS and name.partition('.')[0] in DELIVERY_LABELS:
            provider = DELIVERY_LABELS[name.partition('.')[0]]
            if provider.casefold() not in label.casefold():
                label = provider + ' ' + label[0].lower() + label[1:]
        label = {
            'testflight.app_id': 'App Store Connect Apple ID',
            'testflight.bundle_id': 'Apple bundle ID',
            'firebase.app_id': 'Firebase Android App ID',
            'firebase.bundle_id': 'Android package name',
            'github.repository': 'GitHub repository',
        }.get(name, label)
        description = entry.get('description', '')
        control.setAccessibleName(label)
        control.setToolTip(description or label)
        if entry.get('read_only'):
            control.setAccessibleDescription('Read only. ' + (description or 'Provided by the project.'))
            self.read_only.add(name)
            if isinstance(control, (QLineEdit, QPlainTextEdit)):
                control.setReadOnly(True)
            else:
                control.setEnabled(False)
        self.controls[name] = control
        signal.connect(lambda *_, field=name: self.field_edited(field))

        row = QVBoxLayout()
        input_row = QHBoxLayout()
        input_row.addWidget(control, 1)
        if entry.get('kind') in ('reference', 'protected-file', 'directory') and name not in self.read_only:
            browse = QPushButton('Locate…')
            browse.setAccessibleName('Locate ' + label)
            browse.clicked.connect(lambda: self.locate(control, entry['kind']))
            input_row.addWidget(browse)
        help_entry = setting_help(name)
        if help_entry:
            help_button = QPushButton('Help')
            help_button.setAccessibleName('Help for ' + label)
            help_button.clicked.connect(lambda: self.open_help(label, help_entry))
            input_row.addWidget(help_button)
        row.addLayout(input_row)
        if description and description != label:
            row.addWidget(plain_label(description))
        origin = plain_label('')
        self.origins.append(origin)
        self.origin_labels[name] = origin
        row.addWidget(origin)
        if setting_reset(name, entry):
            reset = QPushButton('Reset')
            reset.clicked.connect(lambda: self.toggle_reset(name))
            self.reset_buttons[name] = reset, label
            row.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)

        heading = plain_label(label)
        heading.setToolTip(description)
        heading.setBuddy(control)
        form.addRow(heading, row)
        search_text = ' '.join((name, *group, label, entry.get('section', ''), description,
                                help_entry.text if help_entry else '')).casefold()
        self.field_rows[name] = group, heading, search_text
        self.update_field(name)

    def open_help(self, label, help_entry):
        dialog = QDialog(self)
        dialog.setWindowTitle('Help for ' + label)
        dialog.resize(490, 230)
        layout = QVBoxLayout(dialog)
        layout.addWidget(HeadingLabel(label, section=True))
        layout.addWidget(plain_label(help_entry.text))
        status = plain_label('')
        status.hide()

        def open_source():
            if not QDesktopServices.openUrl(QUrl(help_entry.url)):
                status.setText('Could not open the provider documentation in your browser.')
                status.show()

        source = QPushButton(help_entry.source + ' ↗')
        source.clicked.connect(open_source)
        layout.addWidget(source, alignment=Qt.AlignmentFlag.AlignLeft)
        guide = QPushButton('Manager delivery setup guide…')
        guide.clicked.connect(lambda: self.open_setup_guide(dialog, help_entry.topic))
        layout.addWidget(guide, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(status)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        style_dialog_buttons(buttons)
        layout.addWidget(buttons)
        style_utilities(dialog)
        buttons.button(QDialogButtonBox.StandardButton.Close).setFocus()
        dialog.exec()
        dialog.deleteLater()

    def open_setup_guide(self, parent, topic):
        from commonUtils.ui.markdown import MarkdownViewer
        dialog = QDialog(parent)
        dialog.setWindowTitle('Delivery setup guide')
        dialog.resize(720, 570)
        layout = QVBoxLayout(dialog)
        viewer = MarkdownViewer(parent=dialog)
        path = Path(__file__).resolve().parents[2] / 'docs/user/delivery-setup.md'
        viewer.open_document(path, fragment=topic)
        layout.addWidget(viewer)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        style_dialog_buttons(buttons)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def field_edited(self, name):
        if name in self.read_only:
            return
        self.resets.pop(name, None)
        value = control_value(self.controls[name])
        if value == self.initial_values[name]:
            self.edits.pop(name, None)
        else:
            self.edits[name] = value
        self.update_field(name)
        self.update_draft()

    def update_field(self, name):
        entry = self.rows[name]
        source = entry.get('origin', '')
        pending = name in self.resets
        if pending:
            reset = setting_reset(name, entry)
            text = 'After save · Source: ' + reset['origin']
        elif name in self.edits:
            text = 'Unsaved checkout edit'
            if source:
                text += ' · Current source: ' + source
        else:
            text = 'Source: ' + source if source else ''
        origin = self.origin_labels[name]
        origin.setText(text)
        origin.setVisible(bool(text) and self.show_origins.isChecked())
        if name in self.reset_buttons:
            button, label = self.reset_buttons[name]
            button.setText('Undo reset' if pending else 'Reset')
            button.setAccessibleName(button.text() + ' ' + label)
            button.setToolTip('Restore the value shown before reset.' if pending else
                              'Clear the checkout override and preview the inherited value.')
            button.setEnabled(pending or self.can_reset(name))
        if pending and source:
            origin.setToolTip('Current source: ' + source)
        else:
            origin.setToolTip('')

    def can_reset(self, name):
        reset = setting_reset(name, self.rows[name])
        return reset is not None and name not in self.resets and (reset['overridden'] or name in self.edits)

    def stage_reset(self, name):
        if not self.can_reset(name):
            return
        reset = setting_reset(name, self.rows[name])
        if reset['overridden']:
            self.resets[name] = control_value(self.controls[name])
        self.edits.pop(name, None)
        set_control_value(self.controls[name], reset['value'])
        self.update_field(name)

    def toggle_reset(self, name):
        if name in self.resets:
            set_control_value(self.controls[name], self.resets.pop(name))
            self.field_edited(name)
        else:
            self.stage_reset(name)
            self.update_draft()

    def reset_page(self, group):
        names = [name for name, (page, _, _) in self.field_rows.items()
                 if page == group and self.can_reset(name)]
        if not names or self.search.text().strip():
            return
        labels = '\n'.join('• ' + self.reset_buttons[name][1] for name in names)
        result = QMessageBox.question(
            self, 'Reset ' + group[-1] + '?',
            'Stage resets for these fields. Save clears their saved checkout overrides '
            'and each field uses its inherited value.\n\n' + labels,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            for name in names:
                self.stage_reset(name)
            self.update_draft()

    def toggle_origins(self, visible):
        for label in self.origins:
            label.setVisible(visible and bool(label.text()))

    def filter_fields(self, *_):
        words = self.search.text().strip().casefold().split()
        groups = set()
        for name, (group, heading, search_text) in self.field_rows.items():
            dependencies = self.rows[name].get('visible_when', {})
            visible = all(word in search_text for word in words) and all(
                key in self.controls and control_value(self.controls[key]) == expected
                for key, expected in dependencies.items())
            self.forms[group].setRowVisible(heading, visible)
            if visible:
                groups.add(group)

        first = None
        for group, (item, _) in self.sections.items():
            item.setHidden(not any(match[:len(group)] == group for match in groups))
            if words and not item.isHidden():
                item.setExpanded(True)
            if first is None and group in groups:
                first = item
        selected = self.sidebar.currentItem()
        if first is not None and (selected is None or selected.isHidden() or
                (words and selected.childCount())):
            self.sidebar.setCurrentItem(first)
        for group, reset in self.page_resets.items():
            reset.setEnabled(not words and any(
                self.can_reset(name) for name, (page, _, _) in self.field_rows.items() if page == group))
        self.stack.setVisible(bool(groups))
        self.search_hint.setVisible(bool(self.rows) and not groups)
        self.toggle_origins(self.show_origins.isChecked())

    def select_section(self, item, previous):
        if item is not None:
            self.stack.setCurrentIndex(item.data(0, Qt.ItemDataRole.UserRole))

    def locate(self, control, kind):
        if kind == 'directory':
            path = QFileDialog.getExistingDirectory(self, 'Locate tool/runtime directory', control.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Locate existing credential or tool file', control.text())
        if path:
            control.setText(path)

    def change_version(self):
        value, accepted = QInputDialog.getText(self, 'Change tracked app version',
            'App version (this edits tracked project metadata and requires a commit):')
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
        if self.busy or not self.dirty:
            return
        values, resets = dict(self.edits), tuple(self.resets)
        from .credentials import validate_settings_changes
        try:
            validate_settings_changes(self.rows, values, getattr(self.project, 'root', None))
            validate_settings_resets(self.rows, values, resets)
        except ValueError as error:
            self.status.setText(str(error))
            return
        project = self.project

        def action(cancelled):
            options = {'resets': resets} if resets else {}
            saver = getattr(project, 'store_settings', None)
            if saver:
                return saver(values, cancelled=cancelled, **options)
            return project.save_settings(values, **options)

        self.start(action, saving=True)
