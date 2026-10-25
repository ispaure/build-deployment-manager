"""Optional Qt presentation for an explicitly supplied project adapter."""
import json
import os
import subprocess
from queue import Empty, Queue
from uuid import uuid4

from PySide6.QtCore import QElapsedTimer, QProcess, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
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


class ManagerPanel(QWidget):
    busy_changed = Signal(bool)
    settings_saved = Signal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.plan, self.result = project, None, None
        self.preparing = False
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
        form = QFormLayout()
        self.operation = QComboBox()
        self.operation.addItems(project.operations)
        self.platform = QComboBox()
        self.platform.addItems(project.platforms)
        self.backend = QComboBox()
        self.platform.currentTextChanged.connect(self.refresh_backends)
        self.operation.currentTextChanged.connect(self.refresh_backends)
        self.revision = QLineEdit('working-tree')
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText('Blank: full declared suite; filename glob: focused contracts')
        self.build_override = QSpinBox()
        self.build_override.setRange(0, 2147483647)
        self.build_override.setSpecialValueText('Automatic')
        self.build_override.setToolTip('Zero selects automatic allocation. A positive number overrides this run only; existing build numbers cannot be reused.')
        self.release_tag = QLineEdit()
        self.release_tag.setPlaceholderText('Explicit release identifier supplied by the project policy')
        for label, control in [('Operation', self.operation), ('Platform', self.platform),
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
            form.addRow(label, control)
        self.run_controls = {}
        for name, entry in getattr(project, 'run_options', {}).items():
            control = QCheckBox(entry['label'])
            control.setChecked(entry.get('default', False))
            control.toggled.connect(self.invalidate)
            self.run_controls[name] = control
            form.addRow(control)
        layout.addLayout(form)
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
        self.verify = QPushButton('Verify connections/settings')
        self.verify.clicked.connect(self.verify_settings)
        for button in (self.prepare, self.start, self.cancel, self.settings, self.verify, self.cleanup):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumBlockCount(6000)
        layout.addWidget(self.preview)
        self.open_results = QPushButton('Open results and logs')
        self.open_results.setEnabled(False)
        self.open_results.clicked.connect(self.show_results)
        layout.addWidget(self.open_results)
        self.status = QLabel('Inspect a plan before running. No deployment follows a passing test automatically.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for control in (self.operation, self.platform, self.backend):
            control.currentTextChanged.connect(self.invalidate)
        self.build_override.valueChanged.connect(self.invalidate)
        for control in (self.revision, self.pattern, self.release_tag):
            control.textChanged.connect(self.invalidate)
        self.refresh_backends()

    def refresh_backends(self, *_):
        self.backend.clear()
        self.backend.addItems(self.project.backend_options(self.platform.currentText(), self.operation.currentText()))

    def invalidate(self, *_):
        self.selection_revision += 1
        self.plan = None
        self.start.setEnabled(False)

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
        from functools import partial
        operation, platform, backend = (control.currentText() for control in
                                       (self.operation, self.platform, self.backend))
        choices = dict(revision=self.revision.text(), pattern=self.pattern.text(),
                       build_override=str(self.build_override.value()) if self.build_override.value() else '', release_tag=self.release_tag.text(),
                       **{name: control.isChecked() for name, control in self.run_controls.items()})
        self.invalidate()
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
        self.preview.setPlainText(self.redact(json.dumps(self.plan.data(), indent=2)))
        self.start.setEnabled(True)
        self.status.setText('Plan ready. Source and ordered phases above identify exactly what will run.')

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
        self.preview.setPlainText(self.redact(json.dumps(self.plan.data(), indent=2)))
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
        run.parent.mkdir(parents=True, exist_ok=True)
        path = run.with_suffix('.plan.json')
        self.plan.save(path)
        self.result = run / 'result.json'
        self.cancel_file = run.with_suffix('.cancel')
        self.buffer = ''
        arguments = ['-m', 'build_manager', str(path), '--output', str(run), '--cancel-file', str(self.cancel_file)]
        if confirmed:
            arguments.append('--confirm')
        self.set_busy(True)
        self.status.setText('Queued…')
        self.process.start(str(self.project.interpreter), arguments)

    def set_busy(self, busy):
        if busy:
            self.phase_elapsed.invalidate()
            self.elapsed.start()
            self.current_phase = 'queued'
            self.clock.start()
        else:
            self.clock.stop()
        for control in (self.prepare, self.start, self.settings, self.verify, self.cleanup, self.operation,
                        self.platform, self.backend, self.revision, self.pattern, self.build_override, self.release_tag,
                        *self.run_controls.values()):
            control.setEnabled(not busy)
        self.cleanup.setEnabled(not busy and hasattr(self.project, 'storage_inventory'))
        self.start.setEnabled(not busy and self.plan is not None)
        self.cancel.setEnabled(busy and not self.preparing)
        self.busy_changed.emit(busy)

    def show_elapsed(self):
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
                self.preview.appendPlainText(event['text'].rstrip())
            elif event.get('type') == 'phase':
                if event['status'] == 'running':
                    self.phase_elapsed.start()
                self.current_phase = event['id'] + ': ' + event['status']
                self.show_elapsed()
            elif event.get('type') == 'error':
                self.status.setText(event['error'])

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
            if not self.result or not self.result.is_file():
                raise ValueError('The operation did not produce a result report.')
            report = json.loads(self.result.read_text())
            status = report['status']
            if status not in {'passed', 'failed', 'cancelled'} or not isinstance(report['phases'], list):
                raise ValueError('The result report is incomplete or invalid.')
            self.preview.appendPlainText(self.redact(json.dumps(report, indent=2)))
            for phase in report['phases']:
                if not isinstance(phase, dict):
                    raise ValueError('Invalid result phase.')
                for artifact in phase.get('artifacts', []):
                    from pathlib import Path
                    if Path(artifact['path']).suffix == '.json':
                        self.preview.appendPlainText(self.redact(Path(artifact['path']).read_text()))
            if exit_status == QProcess.ExitStatus.CrashExit:
                raise ValueError('The operation process crashed.')
            if code and status == 'passed':
                raise ValueError('A passing report disagrees with the operation exit code.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            status = 'failed'
            self.preview.appendPlainText('Result/evidence could not be verified: ' + self.redact(str(error)))
        self.open_results.setEnabled(bool(self.result and self.result.parent.is_dir()))
        self.status.setText(f'{status}; exit {code}. Results: {self.result}')
