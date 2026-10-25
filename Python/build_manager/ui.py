"""Optional Qt presentation for an explicitly supplied project adapter."""
import json
import os
import subprocess
from queue import Empty, Queue
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QElapsedTimer, QProcess, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QTabWidget,
)


class PreparePlan(QRunnable):
    """Only plain project data crosses the worker boundary; Qt stays on the UI thread."""
    def __init__(self, prepare, results):
        super().__init__()
        self.prepare, self.results = prepare, results

    def run(self):
        try:
            from .models import Plan
            plan = self.prepare()
            if not isinstance(plan, Plan):
                raise ValueError('The project adapter did not return an operation plan.')
            self.results.put((plan, None))
        except Exception as error:
            self.results.put((None, str(error)))


class ReadHistory(QRunnable):
    def __init__(self, directory, results):
        super().__init__()
        self.directory, self.results = directory, results
        self.cancelled, self.done = Event(), Event()

    def run(self):
        from .history import recent_runs
        try:
            self.results.put(recent_runs(self.directory, 100, self.cancelled.is_set))
        finally:
            self.done.set()


class SettingsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.controls, self.read_only = project, {}, set()
        self.setWindowTitle('Settings and effective value sources')
        self.resize(800, 650)
        layout = QVBoxLayout(self)
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
        self.sidebar.setAccessibleName('Settings categories')
        self.sidebar.currentItemChanged.connect(self.select_section)
        layout.addWidget(self.navigation, 1)
        forms = {}
        for name, entry in project.settings_view().items():
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
            label = entry.get('label', name)
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
            if entry.get('kind') in ('reference', 'directory'):
                browse = QPushButton('Locate…')
                browse.setToolTip(description)
                browse.setEnabled(not entry.get('read_only', False))
                browse.clicked.connect(lambda checked=False, field=control, kind=entry['kind']: self.locate(field, kind))
                input_row.addWidget(browse)
            row.addLayout(input_row)
            origin = QLabel('Source: ' + entry.get('origin', 'repository default'))
            origin.setWordWrap(True)
            origin.setToolTip(description)
            row.addWidget(origin)
            heading = QLabel(label)
            heading.setToolTip(description)
            forms[group].addRow(heading, row)
        if self.sidebar.topLevelItemCount():
            self.sidebar.setCurrentItem(self.sidebar.topLevelItem(0))
        help_text = QLabel('Save changes to the local profile. One-run build overrides belong in the plan. '
                           'Credential fields contain file references, never private-key contents.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        if hasattr(project, 'set_app_version'):
            version = QPushButton('Change tracked app version…')
            version.clicked.connect(self.change_version)
            layout.addWidget(version)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        try:
            self.project.save_settings(values)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Settings were not saved', str(error))
            return
        self.accept()


class EffectReviewDialog(QDialog):
    """Keep the precise retained evidence visible while authorizing continuation."""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review prepared delivery')
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        heading = QLabel('Approve only after checking the original source, settings, destinations and '
                         'verified artifacts below. Approval applies to this retained preparation.')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        evidence = QPlainTextEdit(text)
        evidence.setReadOnly(True)
        evidence.setAccessibleName('Retained delivery evidence for approval')
        layout.addWidget(evidence, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve = buttons.addButton('Approve and continue', QDialogButtonBox.ButtonRole.AcceptRole)
        approve.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ManagerPanel(QWidget):
    busy_changed = Signal(bool)
    settings_saved = Signal()
    selection_changed = Signal(dict)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.plan, self.result = project, None, None
        self.preparing = False
        self.applying_preset, self.preset_error = False, ''
        self.selection_revision = 0
        self.prepared = Queue()
        self.preparation_timer = QTimer(self)
        self.preparation_timer.setInterval(25)
        self.preparation_timer.timeout.connect(self.plan_prepared)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(project.runner_directory))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.buffer = ''
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in getattr(project, 'secret_environment', ()))
        self.elapsed = QElapsedTimer()
        self.phase_elapsed = QElapsedTimer()
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.show_elapsed)
        self.current_phase = 'queued'
        layout = QVBoxLayout(self)
        self.identity = QLabel(project.description)
        self.identity.setWordWrap(True)
        layout.addWidget(self.identity)
        self.stages = QTabWidget()
        self.stages.setAccessibleName('Testing and delivery stages')
        layout.addWidget(self.stages, 1)
        configure = QScrollArea()
        configure.setWidgetResizable(True)
        configuration = QWidget()
        configure.setWidget(configuration)
        configuration_layout = QVBoxLayout(configuration)
        guidance = QLabel('1. Choose a workflow or operation.  2. Inspect its source, gates and destination.  '
                          '3. Run preparation and tests.  4. Review and continue any delivery steps.')
        guidance.setWordWrap(True)
        configuration_layout.addWidget(guidance)
        self.stages.addTab(configure, '1 · Configure')
        form = QFormLayout()
        advanced_form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem('Custom operation')
        self.preset.addItems(getattr(project, 'workflow_presets', {}))
        self.preset.currentTextChanged.connect(self.select_preset)
        form.addRow('Workflow preset', self.preset)
        self.operation = QComboBox()
        self.operation.addItems(project.operations)
        self.platform = QComboBox()
        self.platform.addItems(project.platforms)
        self.backend = QComboBox()
        self.platform.currentTextChanged.connect(self.refresh_operations)
        self.platform.currentTextChanged.connect(self.refresh_backends)
        self.operation.currentTextChanged.connect(self.refresh_backends)
        self.suite = QComboBox()
        self.suite.setAccessibleName('Test suite')
        self.suite.currentIndexChanged.connect(self.invalidate)
        self.platform.currentTextChanged.connect(self.refresh_suites)
        self.operation.currentTextChanged.connect(self.refresh_suites)
        self.revision = QLineEdit('working-tree')
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText('Blank: full declared suite; filename glob: focused contracts')
        self.build_override = QSpinBox()
        self.build_override.setRange(0, 2147483647)
        self.build_override.setSpecialValueText('Automatic')
        self.build_override.setToolTip('Zero selects automatic allocation. A positive number overrides this run only; existing build numbers cannot be reused.')
        self.release_tag = QLineEdit()
        self.release_tag.setPlaceholderText('Explicit release identifier supplied by the project policy')
        for label, control in [('Platform', self.platform), ('Operation', self.operation),
                               ('Backend', self.backend), ('Source revision', self.revision),
                               ('Focused test pattern', self.pattern), ('Build number override', self.build_override),
                               ('GitHub release tag', self.release_tag)]:
            control.setAccessibleName(label)
            if control is not self.build_override:
                control.setToolTip({
                    'Operation': 'Choose tests, an artifact build, tester preparation or a GitHub release. Inspect the plan before running.',
                    'Platform': 'Operating system to build or test.',
                    'Backend': 'Where the operation runs. VM backends require an explicitly configured authorized test VM.',
                    'Source revision': 'working-tree includes current edits; a Git revision selects that committed source.',
                    'Focused test pattern': 'Optional test filename glob for desktop contracts. Blank runs the full declared suite.',
                    'GitHub release tag': 'Explicit unused release tag for a Release operation, such as v0.1.15-alpha.39.',
                }[label])
            (form if control in (self.operation, self.platform, self.backend) else advanced_form).addRow(label, control)
        form.addRow('Test suite', self.suite)
        self.run_controls = {}
        for name, entry in getattr(project, 'run_options', {}).items():
            control = QCheckBox(entry['label'])
            control.setChecked(entry.get('default', False))
            control.toggled.connect(self.invalidate)
            self.run_controls[name] = control
            form.addRow(control)
        configuration_layout.addLayout(form)
        self.advanced_toggle = QCheckBox('Advanced options: source, focused tests and release identifiers')
        advanced = QWidget()
        advanced.setLayout(advanced_form)
        advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        configuration_layout.addWidget(self.advanced_toggle)
        configuration_layout.addWidget(advanced)
        configuration_layout.addStretch()
        controls = QHBoxLayout()
        self.prepare = QPushButton('Inspect plan')
        self.prepare.clicked.connect(self.inspect_plan)
        self.start = QPushButton('Run reviewed plan')
        self.start.setEnabled(False)
        self.start.clicked.connect(self.run_plan)
        self.cancel = QPushButton('Cancel operation')
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_operation)
        self.settings = QPushButton('Settings…')
        self.settings.clicked.connect(self.edit_settings)
        self.cleanup = QPushButton('Clean up builds…')
        self.cleanup.setEnabled(hasattr(project, 'storage_inventory'))
        self.cleanup.setToolTip('Review owned build outputs and delete selected or all unprotected entries.')
        self.cleanup.clicked.connect(self.clean_builds)
        self.resume = QPushButton('Resume retained workflow…')
        self.resume.clicked.connect(self.resume_workflow)
        self.verify = QPushButton('Verify connections/settings')
        self.verify.clicked.connect(self.verify_settings)
        for button in (self.prepare, self.settings, self.verify, self.cleanup):
            controls.addWidget(button)
        configuration_layout.addLayout(controls)
        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.addWidget(QLabel('Review the exact source, steps and destinations before starting.'))
        review_tabs = QTabWidget()
        self.overview = QPlainTextEdit()
        self.overview.setReadOnly(True)
        self.overview.setAccessibleName('Readable plan review')
        self.plan_data = QPlainTextEdit()
        self.plan_data.setReadOnly(True)
        self.plan_data.setAccessibleName('Complete redacted plan data')
        review_tabs.addTab(self.overview, 'Overview')
        review_tabs.addTab(self.plan_data, 'Complete plan')
        review_layout.addWidget(review_tabs, 1)
        review_layout.addWidget(self.start)
        self.stages.addTab(review, '2 · Review')
        from .run_ui import RunView
        run_page = QWidget()
        run_layout = QVBoxLayout(run_page)
        self.run_view = RunView()
        run_layout.addWidget(self.run_view, 1)
        self.preview = self.run_view.log
        self.phase_status = self.run_view.steps
        self.phase_rows = self.run_view.rows
        self.open_results = QPushButton('Open results and logs')
        self.open_results.setEnabled(False)
        self.open_results.clicked.connect(self.show_results)
        self.continue_run = QPushButton('Review and continue this run…')
        self.continue_run.setEnabled(False)
        self.continue_run.clicked.connect(lambda: self.resume_workflow(self.result))
        run_buttons = QHBoxLayout()
        for button in (self.cancel, self.continue_run, self.open_results):
            run_buttons.addWidget(button)
        run_layout.addLayout(run_buttons)
        self.stages.addTab(run_page, '3 · Run and results')
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.addWidget(QLabel('Retained runs for this project. Select a run to view its steps and test results.'))
        self.history = QTreeWidget()
        self.history.setHeaderLabels(['Started', 'Operation', 'Outcome', 'Active time'])
        self.history.setAccessibleName('Project run history')
        self.history.setColumnWidth(0, 220)
        self.history.itemActivated.connect(self.open_history)
        history_layout.addWidget(self.history, 1)
        history_buttons = QHBoxLayout()
        self.refresh_history_button = QPushButton('Refresh history')
        self.refresh_history_button.clicked.connect(self.refresh_history)
        self.view_history_button = QPushButton('View selected run')
        self.view_history_button.clicked.connect(lambda: self.open_history(self.history.currentItem()))
        for button in (self.refresh_history_button, self.view_history_button, self.resume):
            history_buttons.addWidget(button)
        history_layout.addLayout(history_buttons)
        self.stages.addTab(history_page, '4 · History')
        self.history_results = Queue()
        self.history_job = None
        self.closing = False
        self.history_loading, self.history_refresh_pending = False, False
        self.history_timer = QTimer(self)
        self.history_timer.setInterval(50)
        self.history_timer.timeout.connect(self.history_loaded)
        self.status = QLabel('Inspect a plan before running. No deployment follows a passing test automatically.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for control in (self.operation, self.platform, self.backend):
            control.currentTextChanged.connect(self.invalidate)
        self.build_override.valueChanged.connect(self.invalidate)
        for control in (self.revision, self.pattern, self.release_tag):
            control.textChanged.connect(self.invalidate)
        self.refresh_operations()
        self.refresh_backends()
        self.refresh_suites()
        self.refresh_history()

    def select_preset(self, name):
        choices=getattr(self.project,'workflow_presets',{}).get(name)
        self.preset_error = ''
        if not choices:
            return
        self.applying_preset = True
        try:
            if self.platform.findText(choices['platform']) < 0:
                raise ValueError('This workflow platform is unavailable in the selected project.')
            self.platform.setCurrentText(choices['platform'])
            if self.operation.findText(choices['operation']) < 0:
                raise ValueError('This workflow operation is unavailable on the selected platform.')
            self.operation.setCurrentText(choices['operation'])
            if self.backend.findText(choices['backend']) < 0:
                raise ValueError('This workflow backend is unavailable on this host. Choose a supported workflow or Custom operation.')
            self.backend.setCurrentText(choices['backend'])
            index = self.suite.findData(choices.get('suite', ''))
            if index < 0:
                raise ValueError('This workflow test suite is unavailable for the selected operation.')
            self.suite.setCurrentIndex(index)
            self.invalidate()
        except (KeyError, TypeError, ValueError) as error:
            self.invalidate()
            self.preset_error = str(error)
            self.status.setText(self.preset_error)
        finally:
            self.applying_preset = False

    def refresh_operations(self, *_):
        factory=getattr(self.project,'operations_for',None)
        if factory:
            previous=self.operation.currentText()
            self.operation.clear();self.operation.addItems(factory(self.platform.currentText()))
            if self.operation.findText(previous)>=0:self.operation.setCurrentText(previous)

    def refresh_backends(self, *_):
        self.backend.clear()
        self.backend.addItems(self.project.backend_options(self.platform.currentText(), self.operation.currentText()))

    def refresh_suites(self, *_):
        if not hasattr(self, 'suite'):
            return
        previous = self.suite.currentData()
        self.suite.blockSignals(True)
        self.suite.clear()
        self.suite.addItem('Full declared suite / operation default', '')
        for row in getattr(self.project, 'test_suites', []):
            if self.platform.currentText() in row['platforms'] and self.operation.currentText() in row['operations']:
                self.suite.addItem(row['label'] + ' · ' + row['tier'], row['id'])
                self.suite.setItemData(self.suite.count()-1, row.get('description', ''), 3)
        self.suite.setCurrentIndex(max(0, self.suite.findData(previous)))
        self.suite.blockSignals(False)

    def choices(self):
        return dict(suite=self.suite.currentData() or '', **{name: getattr(self, name).currentText() if name in ('operation', 'platform', 'backend')
                else getattr(self, name).text()
                for name in ('operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag')})

    def invalidate(self, *_, preserve_preset=False):
        self.selection_revision += 1
        self.plan = None
        self.start.setEnabled(False)
        if not self.applying_preset and not preserve_preset:
            self.preset_error = ''
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(0)
            self.preset.blockSignals(False)
        self.selection_changed.emit(self.choices())
        if hasattr(self, 'status'):
            self.status.setText('Selection changed. Inspect a fresh plan before running.')

    def edit_settings(self):
        try:
            if SettingsDialog(self.project, self).exec():
                self.invalidate()
                self.settings_saved.emit()
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def clean_builds(self):
        from .storage_ui import StorageDialog
        StorageDialog(self.project, self).exec()

    def inspect_plan(self):
        if self.preparing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if self.preset_error:
            self.status.setText(self.preset_error)
            return
        from functools import partial
        operation, platform, backend = (control.currentText() for control in
                                       (self.operation, self.platform, self.backend))
        choices = dict(revision=self.revision.text(), pattern=self.pattern.text(),
                       build_override=str(self.build_override.value()) if self.build_override.value() else '', release_tag=self.release_tag.text(),
                       **{name: control.isChecked() for name, control in self.run_controls.items()})
        if self.suite.currentData():
            choices['suite'] = self.suite.currentData()
        self.invalidate(preserve_preset=True)
        self.preparation_revision = self.selection_revision
        self.preparing = True
        self.set_busy(True)
        self.current_phase = 'Inspecting source and prerequisites'
        self.phase_elapsed.start()
        self.show_elapsed()
        QThreadPool.globalInstance().start(PreparePlan(
            partial(self.project.make_plan, operation, platform, backend, **choices), self.prepared))
        self.preparation_timer.start()

    def plan_prepared(self):
        try:
            plan, error = self.prepared.get_nowait()
        except Empty:
            return
        self.preparation_timer.stop()
        self.preparing = False
        self.set_busy(False)
        if error is not None:
            self.status.setText(self.redact(error))
            return
        if self.selection_revision != self.preparation_revision:
            self.status.setText('Selection changed during preparation; inspect a fresh plan.')
            return
        self.plan = plan
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in self.plan.secret_environment)
        self.present_plan(self.plan)
        self.stages.setCurrentIndex(1)
        self.start.setEnabled(True)
        self.status.setText('Plan ready. Review the source, ordered steps and destinations, then run.')

    def verify_settings(self):
        if self.preparing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            self.plan = self.project.verification_plan()
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.status.setText(str(error))
            return
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in self.plan.secret_environment)
        self.present_plan(self.plan)
        self.run_plan()

    def run_plan(self):
        if self.plan is None or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        confirmed = self.plan.effect in {'deploy', 'upload', 'publish'}
        if confirmed and QMessageBox.question(self, 'Confirm reviewed operation',
                f'{self.plan.operation} on {self.plan.backend}? Review the source and destinations above.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        run = self.project.results_directory / uuid4().hex
        path = run.with_suffix('.plan.json')
        try:
            run.parent.mkdir(parents=True, exist_ok=True)
            self.plan.save(path)
        except (OSError, ValueError) as error:
            self.status.setText('Cannot start this plan: ' + self.redact(str(error)))
            return
        self.resumable = False
        self.result = run / 'result.json'
        self.active_plan = self.plan
        self.cancel_file = run.with_suffix('.cancel')
        self.buffer = ''
        self.seed_run(self.plan)
        self.open_results.setEnabled(False)
        self.continue_run.setEnabled(False)
        self.stages.setCurrentIndex(2)
        arguments = ['-m', 'build_manager', str(path), '--output', str(run), '--cancel-file', str(self.cancel_file)]
        if confirmed:
            arguments.append('--confirm')
        self.set_busy(True)
        self.status.setText('Queued…')
        self.process.start(str(self.project.interpreter), arguments)

    def resume_workflow(self, retained=None):
        from pathlib import Path
        if self.preparing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if retained and not isinstance(retained, bool):
            path = str(retained)
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Select retained result.json', str(self.project.results_directory), 'JSON (*.json)')
        if not path:
            return
        try:
            result = Path(path)
            from .history import load_run
            plan, previous = load_run(result)
            plan_path = result.parent/'plan.json'
            descriptor = getattr(self.project, 'descriptor', {})
            if descriptor and plan.project != descriptor['name']:
                raise ValueError('This run belongs to a different selected project.')
            if descriptor and plan.adapter and (plan.adapter.get('project_id') != descriptor['project_id']
                    or plan.adapter.get('checkout') != str(self.project.root)):
                raise ValueError('This run belongs to a different registered checkout.')
            from .workflows import recover, approve
            recover(plan, previous) # Unknown remote effects must be reconciled separately.
            self.present_plan(plan)
            self.seed_run(plan, previous['phases'])
            self.plan = None
            self.result = result
            self.start.setEnabled(False)
            self.open_results.setEnabled(True)
            self.preview.setPlainText(self.redact(json.dumps(dict(plan=plan.data(),previous=previous),indent=2)))
            self.stages.setCurrentIndex(1)
            steps = [row['id'] for row in previous['phases'] if row['status']=='awaiting_review']
            if (steps or plan.effect in {'deploy', 'upload', 'publish'}) and not self.confirm_continuation(plan, previous, steps):
                return
            for step in steps:approve(plan,step,previous)
            self.plan, self.result = plan,result
            self.active_plan = plan
            self.seed_run(plan, [row for row in previous['phases'] if row['status'] == 'passed'])
            self.cancel_file = result.parent.with_suffix('.resume-'+uuid4().hex+'.cancel')
            arguments=['-m','build_manager',str(plan_path),'--output',str(result.parent),'--resume','--cancel-file',str(self.cancel_file)]
            if steps or plan.effect in {'deploy','upload','publish'}:arguments.append('--confirm')
            for step in steps:arguments+=['--approve-step',step]
            self.buffer = ''
            self.continue_run.setEnabled(False)
            self.stages.setCurrentIndex(2)
            self.set_busy(True)
            self.process.start(str(self.project.interpreter),arguments)
        except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:
            self.status.setText(self.redact(str(error)))

    def confirm_continuation(self, plan, previous, steps):
        from .run_ui import plan_overview
        lines = [plan_overview(self.safe_plan(plan)), '', 'Steps awaiting approval: ' + ', '.join(steps),
                 '', 'Retained prerequisite results and evidence:']
        for row in self.redacted_data(previous['phases']):
            lines.append(row['id'] + ': ' + row['status'])
            for artifact in row.get('artifacts', []):
                lines += [f'  {artifact.get("kind", "file")}: {artifact["path"]}',
                          '  Original: ' + artifact.get('original_path', artifact['path']),
                          '  SHA-256: ' + artifact['sha256']]
                preview = self.artifact_preview(artifact['path'])
                if preview:
                    lines += ['  Prepared identity / evidence:', preview]
        return EffectReviewDialog('\n'.join(lines), self).exec() == QDialog.DialogCode.Accepted

    def artifact_preview(self, path):
        from pathlib import Path
        path = Path(path)
        if path.suffix.lower() != '.json':
            return ''
        try:
            with path.open('rb') as stream:
                raw = stream.read(262145)
            if len(raw) > 262144:
                return 'JSON evidence exceeds the preview limit; inspect the retained file in results.'
            return json.dumps(self.redacted_data(json.loads(raw)), indent=2)
        except (OSError, ValueError, RecursionError) as error:
            return 'Cannot preview retained JSON evidence: ' + self.redact(str(error))

    def set_busy(self, busy):
        if busy:
            self.phase_elapsed.invalidate()
            self.elapsed.start()
            self.current_phase = 'queued'
            self.clock.start()
        else:
            self.clock.stop()
        for control in (self.prepare, self.start, self.settings, self.verify, self.cleanup, self.resume, self.operation,
                        self.platform, self.backend, self.preset, self.suite, self.revision, self.pattern, self.build_override, self.release_tag,
                        self.refresh_history_button, self.view_history_button, self.history, self.continue_run,
                        *self.run_controls.values()):
            control.setEnabled(not busy)
        self.cleanup.setEnabled(not busy and hasattr(self.project, 'storage_inventory'))
        self.start.setEnabled(not busy and self.plan is not None)
        self.continue_run.setEnabled(not busy and bool(getattr(self, 'resumable', False)))
        self.cancel.setEnabled(busy and not self.preparing)
        self.busy_changed.emit(busy)

    def show_elapsed(self):
        self.run_view.tick()
        phase = self.phase_elapsed.elapsed()/1000 if self.phase_elapsed.isValid() else 0
        self.status.setText(f'{self.current_phase}; phase {phase:.0f}s; total {self.elapsed.elapsed()/1000:.0f}s')

    def read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                self.preview.appendPlainText(self.redact(line))
                continue
            if event.get('type') == 'output':
                self.preview.appendPlainText(self.redact('['+event.get('phase','step')+'] '+event['text'].rstrip()))
            elif event.get('type') == 'waiting':
                self.update_phase(dict(id=event['phase'],status=event['reason']))
            elif event.get('type') == 'phase':
                self.update_phase(event)
                if event['status'] == 'running':
                    self.phase_elapsed.start()
                self.current_phase = event['id'] + ': ' + event['status']
                self.show_elapsed()
            elif event.get('type') == 'error':
                self.status.setText(self.redact(event['error']))

    def update_phase(self, event):
        self.run_view.update_phase(self.redacted_data(event))
        self.phase_rows = self.run_view.rows

    def redacted_data(self, value):
        from .redaction import Redactor
        # Filter values rather than JSON syntax: password-like values and PEM
        # blocks must never consume the surrounding serialization delimiters.
        if isinstance(value, str):
            return Redactor(self.redact.secrets)(value)
        if isinstance(value, dict):
            return {key: self.redacted_data(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redacted_data(item) for item in value]
        return value

    def safe_plan(self, plan):
        from types import SimpleNamespace
        data = self.redacted_data(plan.data())
        data['phases'] = [SimpleNamespace(**phase) for phase in data['phases']]
        return SimpleNamespace(**data)

    def present_plan(self, plan):
        from .redaction import Redactor
        from .run_ui import plan_overview
        self.redact = Redactor(os.environ.get(name) for name in plan.secret_environment)
        safe = self.safe_plan(plan)
        self.overview.setPlainText(plan_overview(safe))
        self.plan_data.setPlainText(json.dumps(self.redacted_data(plan.data()), indent=2))

    def seed_run(self, plan, previous=()):
        safe = self.safe_plan(plan)
        self.run_view.reset(safe, self.redacted_data(previous))
        self.phase_rows = self.run_view.rows

    def closeEvent(self, event):
        self.closing = True
        self.history_timer.stop()
        self.history_refresh_pending = False
        if self.history_job is not None:
            self.history_job.cancelled.set()
            # Release report handles before the panel's project can be removed.
            if not self.history_job.done.wait(1):
                event.ignore()
                QTimer.singleShot(50, self.close)
                return
        super().closeEvent(event)

    def refresh_history(self):
        if self.closing:
            return
        if self.history_loading:
            self.history_refresh_pending = True
            return
        self.history_loading = True
        self.history_timer.start()
        self.history_job = ReadHistory(self.project.results_directory, self.history_results)
        QThreadPool.globalInstance().start(self.history_job)

    def history_loaded(self):
        try:
            rows = self.history_results.get_nowait()
        except Empty:
            return
        self.history_loading = False
        self.history_timer.stop()
        if self.history_refresh_pending:
            self.history_refresh_pending = False
            self.refresh_history()
            return
        from .run_ui import duration
        from PySide6.QtCore import Qt
        from datetime import datetime
        self.history.clear()
        for row in rows:
            started = row.get('started_at', '')
            try:
                started = datetime.fromisoformat(started).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
            except ValueError:
                pass
            item = QTreeWidgetItem([started, self.redacted_data(row.get('operation', '')),
                                    row['status'], duration(row.get('seconds'))])
            item.setData(0, Qt.ItemDataRole.UserRole, row['path'])
            self.history.addTopLevelItem(item)

    def open_history(self, item, column=0):
        if item is None or self.preparing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        from pathlib import Path
        from PySide6.QtCore import Qt
        from .history import load_run
        try:
            path = Path(item.data(0, Qt.ItemDataRole.UserRole))
            plan, report = load_run(path)
            self.plan = None
            self.start.setEnabled(False)
            self.result = path
            self.present_plan(plan)
            self.seed_run(plan, report['phases'])
            self.run_view.complete(report)
            self.preview.setPlainText(self.redact(json.dumps(report, indent=2)))
            self.resumable = report['status'] in {'awaiting_review', 'failed', 'cancelled'}
            self.continue_run.setEnabled(self.resumable)
            self.continue_run.setText('Review and continue delivery…' if report['status'] == 'awaiting_review' else 'Retry unfinished steps…')
            self.open_results.setEnabled(True)
            self.stages.setCurrentIndex(2)
            self.status.setText(f'Viewing retained run: {report["status"]}. Resume separately to continue work.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText('Cannot read retained run: ' + self.redact(str(error)))

    def read_errors(self):
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        self.preview.appendPlainText(self.redact(text))

    def cancel_operation(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.current_phase = 'Cancelling active work and running owned cleanup…'
            self.show_elapsed()
            # Windows console processes do not reliably receive QProcess's
            # WM_CLOSE. The CLI observes this owned marker and retains its
            # structured cancelled result while it stops the phase's job/tree.
            self.cancel_file.touch()

    def process_error(self, *_):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.set_busy(False)
            self.run_view.unverified('The operation process could not start.')
            self.status.setText('Operation could not start: ' + self.process.errorString())

    def show_results(self):
        if self.result and self.result.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.parent)))

    def finished(self, code, exit_status=None):
        self.read_output()
        self.set_busy(False)
        status = 'failed'
        if self.buffer:
            self.preview.appendPlainText(self.redact(self.buffer))
            self.buffer = ''
        try:
            if exit_status == QProcess.ExitStatus.CrashExit:
                raise ValueError('The operation process crashed.')
            if not self.result or not self.result.is_file():
                raise ValueError('The operation did not produce a result report.')
            from .history import read_report
            report = read_report(self.result)
            if getattr(self, 'active_plan', None) and report.get('plan_identity') != self.active_plan.identity:
                raise ValueError('The result report belongs to a different reviewed plan.')
            status = report['status']
            if status not in {'passed', 'failed', 'cancelled', 'awaiting_review', 'unknown'} or not isinstance(report['phases'], list):
                raise ValueError('The result report is incomplete or invalid.')
            self.preview.appendPlainText(self.redact(json.dumps(report, indent=2)))
            for phase in report['phases']:
                if not isinstance(phase, dict):
                    raise ValueError('Invalid result phase.')
                self.update_phase(phase)
                for artifact in phase.get('artifacts', []):
                    evidence = self.artifact_preview(artifact['path'])
                    if evidence:
                        self.preview.appendPlainText(evidence)
            self.run_view.complete(report)
            if code and status == 'passed':
                raise ValueError('A passing report disagrees with the operation exit code.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            status = 'failed'
            self.run_view.unverified(self.redact(str(error)))
            self.preview.appendPlainText('Result/evidence could not be verified: ' + self.redact(str(error)))
        self.open_results.setEnabled(bool(self.result and self.result.parent.is_dir()))
        self.resumable = status in {'awaiting_review', 'failed', 'cancelled'} and bool(self.result and self.result.is_file())
        self.continue_run.setEnabled(self.resumable)
        self.continue_run.setText('Review and continue delivery…' if status == 'awaiting_review' else 'Retry unfinished steps…')
        self.refresh_history()
        next_action = ' Review and continue this run to approve prepared delivery.' if status == 'awaiting_review' else ''
        self.status.setText(f'{status}; exit {code}. Results: {self.result}' + next_action)
