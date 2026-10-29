"""Optional Qt presentation for an explicitly supplied project adapter."""
import json
import os
from queue import Empty, Queue
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QElapsedTimer, QProcess, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QInputDialog,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QTreeWidget,
    QTreeWidgetItem, QTabBar, QTabWidget, QStackedWidget, QSplitter, QSizePolicy, QFrame,
)
from .settings_ui import SettingsDialog
from .approval_ui import EffectReviewDialog
from .ui_components import style_button, style_dialog_buttons, ViewportStack, CurrentPageStack


class PreparationFailure(str):
    def __new__(cls, message, details):
        failure = super().__new__(cls, message)
        failure.details = details
        return failure


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
            import traceback
            self.results.put((None, PreparationFailure(str(error), traceback.format_exc())))


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


class ManagerPanel(QWidget):
    busy_changed = Signal(bool)
    idle = Signal()
    retained_run_requested = Signal(object)
    settings_saved = Signal()
    selection_changed = Signal(dict)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.plan, self.result = project, None, None
        self.preparing = False
        self.applying_preset, self.preset_error = False, ''
        self.selection_revision = 0
        self.prepared = Queue()
        self.card_proposals = {}
        self.preparing_proposal = None
        self.preparation_timer = QTimer(self)
        self.preparation_timer.setInterval(25)
        self.preparation_timer.timeout.connect(self.plan_prepared)
        from .run_session import RunSession
        self.session = RunSession(project.runner_directory, self)
        self.process = self.session.process
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.session.clock.timeout.connect(self.show_elapsed)
        self.output_timer = QTimer(self)
        self.output_timer.setSingleShot(True)
        self.output_timer.timeout.connect(self.read_output)
        self.live_update_timer = QTimer(self)
        self.live_update_timer.setSingleShot(True)
        self.live_update_timer.setInterval(100)
        self.live_update_timer.timeout.connect(self.flush_live_updates)
        self.review_live_dirty = False
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in getattr(project, 'secret_environment', ()))
        self.reviewing = False
        self.review_job = None
        self.review_results = Queue()
        self.review_timer = QTimer(self)
        self.review_timer.setInterval(25)
        self.review_timer.timeout.connect(self.continuation_verified)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.identity = QLabel(project.description)
        self.identity.setText(getattr(project, 'descriptor', {}).get('name', project.description))
        self.identity.setToolTip(project.description)
        self.identity.setWordWrap(True)
        layout.addWidget(self.identity)
        self.stage_tabs = QTabBar()
        self.stage_tabs.setAccessibleName('Run steps and history')
        for title in ('Choose work', 'Review plan', 'Progress && results', 'History'):
            self.stage_tabs.addTab(title)
        self.stage_tabs.setTabEnabled(1, False)
        self.stage_tabs.setTabEnabled(2, False)
        layout.addWidget(self.stage_tabs)
        # Keep action handles for callers that navigate programmatically.
        self.new_run = QPushButton('Choose work', self)
        self.past_runs = QPushButton('History', self)
        self.view_run = QPushButton('Progress & results', self)
        for button, index in ((self.new_run, 0), (self.past_runs, 3), (self.view_run, 2)):
            button.hide()
            button.clicked.connect(lambda checked=False, index=index: self.stages.setCurrentIndex(index))
        self.view_run.setEnabled(False)
        self.stage_heading = QLabel()
        self.stage_heading.setWordWrap(True)
        layout.addWidget(self.stage_heading)
        self.stages = ViewportStack()
        self.stages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.stages.currentChanged.connect(self.show_stage)
        self.stage_tabs.currentChanged.connect(self.stages.setCurrentIndex)
        self.stages.setAccessibleName('Testing and delivery stages')
        layout.addWidget(self.stages, 1)
        from .configuration_ui import ConfigurationView
        self.configuration = ConfigurationView(project, self)
        configuration_layout = self.configuration.body_layout
        self.stages.addWidget(self.configuration)
        self.configuration.goal.currentIndexChanged.connect(self.goal_changed)
        for control in (*self.configuration.platform_checks.values(), *self.configuration.destination_checks.values()):
            control.toggled.connect(self.invalidate)
        for control in self.configuration.platform_backends.values():
            control.currentTextChanged.connect(self.invalidate)
        for control in self.configuration.run_fields.controls.values():
            control.textChanged.connect(self.invalidate)
        self.configuration.run_fields.defaults_loaded.connect(self.invalidate)
        self.configuration.preset.currentTextChanged.connect(self.select_preset)
        self.configuration.restore_preset.clicked.connect(lambda: self.select_preset(self.configuration.preset.currentText()))
        self.configuration.platform.currentTextChanged.connect(self.refresh_operations)
        self.configuration.platform.currentTextChanged.connect(self.refresh_backends)
        self.configuration.operation.currentTextChanged.connect(self.refresh_backends)
        self.configuration.suite.currentIndexChanged.connect(self.invalidate)
        self.configuration.platform.currentTextChanged.connect(self.refresh_suites)
        self.configuration.operation.currentTextChanged.connect(self.refresh_suites)
        for control in self.configuration.run_controls.values():
            control.toggled.connect(self.invalidate)
        self.prepare = QPushButton('Next: review plan', self)
        self.prepare.clicked.connect(self.inspect_plan)
        self.start = QPushButton('Run reviewed plan', self)
        self.start.setEnabled(False)
        self.start.clicked.connect(self.run_plan)
        self.cancel = QPushButton('Cancel operation', self)
        self.cancel.setEnabled(False)
        self.cancel.hide()
        self.cancel.clicked.connect(self.cancel_operation)
        self.settings = QPushButton('Project settings…', self)
        self.settings.clicked.connect(self.edit_settings)
        self.cleanup = QPushButton('Clean up builds…', self)
        self.cleanup.setEnabled(hasattr(project, 'storage_inventory'))
        self.cleanup.setToolTip('Review owned build outputs and delete selected or all unprotected entries.')
        self.cleanup.clicked.connect(self.clean_builds)
        self.resume = QPushButton('Continue a saved run…', self)
        self.resume.clicked.connect(self.resume_workflow)
        self.verify = QPushButton('Verify connections/settings', self)
        self.verify.clicked.connect(self.verify_settings)
        self.plan_feedback = QLabel('Choose your work, then review the plan before starting any checks.')
        self.plan_feedback.setWordWrap(True)
        self.plan_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.plan_feedback.setAccessibleName('Plan preparation feedback')
        configuration_layout.addWidget(self.plan_feedback)
        self.plan_feedback.hide()
        from .review_ui import Disclosure, text_view
        self.preparation_error = text_view('Full plan preparation failure and traceback')
        self.preparation_error.setMaximumHeight(160)
        self.preparation_error_section = Disclosure('Error details · full traceback', self.preparation_error)
        self.preparation_error_section.hide()
        configuration_layout.addWidget(self.preparation_error_section)
        self.verify.hide()
        self.cleanup.hide()
        self.prepare.setDefault(True)
        self.prepare.setToolTip('Check choices and prepare the plan. Tests start after the next review.')
        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(6, 4, 6, 4)
        review_layout.setSpacing(4)
        review_heading = QLabel('Review your run')
        review_heading.setStyleSheet('font-size: 18pt; font-weight: 600;')
        review_layout.addWidget(review_heading)
        self.review_state = QLabel('Prepare a plan to review your choices.')
        self.review_state.setWordWrap(True)
        self.review_state.setTextFormat(Qt.TextFormat.PlainText)
        review_layout.addWidget(self.review_state)
        from .review_ui import ReviewPlanView
        self.review_workspace = ReviewPlanView()
        review_layout.addWidget(self.review_workspace, 1)
        self.review_choices = self.review_workspace
        self.review_flow = self.review_workspace.graph
        self.review_inspector = self.review_workspace.details
        self.review_splitter = self.review_workspace.splitter
        self.review_board = self.review_workspace.board
        self.overview = self.review_workspace.overview
        self.plan_data = self.review_workspace.plan_data
        self.review_summary = QLabel(review)
        self.review_summary.setWordWrap(True)
        self.review_summary.hide()
        self.review_context = QLabel(review)
        self.review_context.hide()
        self.review_run_inputs = QPlainTextEdit(review)
        self.review_run_inputs.hide()
        self.review_help = QLabel()
        self.review_help.setWordWrap(True)
        self.review_help.setTextFormat(Qt.TextFormat.PlainText)
        self.back = QPushButton('Back to choices')
        self.back.clicked.connect(lambda: self.stages.setCurrentIndex(0))
        self.stages.addWidget(review)
        from .run_ui import RunView
        run_page = QWidget()
        run_layout = QVBoxLayout(run_page)
        run_layout.setContentsMargins(6, 4, 6, 4)
        run_layout.setSpacing(4)
        self.run_view = RunView()
        run_layout.addWidget(self.run_view, 1)
        self.preview = self.run_view.log
        self.phase_status = self.run_view.steps
        self.phase_rows = self.run_view.rows
        self.open_results = QPushButton('Open results folder…', self)
        self.open_results.setEnabled(False)
        self.open_results.clicked.connect(self.show_results)
        self.continue_run = QPushButton('Review and continue this run…', self)
        self.continue_run.setEnabled(False)
        self.continue_run.hide()
        self.continue_run.clicked.connect(lambda: self.resume_workflow(self.result))
        self.retry_device = QPushButton('Retry uncertain device install…', self)
        self.retry_device.hide()
        self.retry_device.clicked.connect(self.retry_device_install)
        self.run_problems = QPushButton('View problems', self)
        self.run_problems.clicked.connect(self.run_view.show_problems)
        self.run_view.review_requested.connect(self.continue_run.click)
        self.run_view.run_choices.flow.card_action_requested.connect(self.retry_device_install)
        self.run_view.attention_changed.connect(self.update_run_actions)
        self.stages.addWidget(run_page)
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        from .history_ui import RunHistoryView
        self.history_view = RunHistoryView()
        self.history, self.history_hint = self.history_view.tree, self.history_view.hint
        self.history.itemActivated.connect(self.open_history)
        history_layout.addWidget(self.history_view, 1)
        self.refresh_history_button = QPushButton('Refresh history', self)
        self.refresh_history_button.clicked.connect(self.refresh_history)
        self.view_history_button = QPushButton('View selected run', self)
        self.view_history_button.setEnabled(False)
        self.view_history_button.clicked.connect(lambda: self.open_history(self.history.currentItem()))
        self.history.currentItemChanged.connect(self.history_selection_changed)
        self.stages.addWidget(history_page)
        # One footer sits outside all stage content. ManagerWindow docks this
        # same widget below its workspace scrollbar; standalone panels retain it.
        self.action_footer = QFrame()
        self.action_footer.setObjectName('actionFooter')
        self.action_footer.setStyleSheet('QFrame#actionFooter { border-top: 1px solid palette(mid); }')
        footer_layout = QVBoxLayout(self.action_footer)
        footer_layout.setContentsMargins(8, 8, 8, 4)
        self.footer_pages = CurrentPageStack()
        footer_layout.addWidget(self.footer_pages)
        for left, right in (
                ((), (self.prepare,)),
                ((self.back,), (self.start,)),
                ((self.cancel,), (self.open_results, self.run_problems, self.retry_device, self.continue_run)),
                ((self.refresh_history_button, self.resume), (self.view_history_button,))):
            page = QWidget()
            actions = QHBoxLayout(page)
            actions.setContentsMargins(0, 0, 0, 0)
            for button in left:
                actions.addWidget(style_button(button))
            actions.addStretch()
            if self.start in right:
                actions.addWidget(self.review_help, 1)
            for button in right:
                actions.addWidget(style_button(button))
            self.footer_pages.addWidget(page)
        for button in (self.prepare, self.start, self.view_history_button):
            style_button(button, 'primary')
        self.history_results = Queue()
        self.history_job = None
        self.closing = False
        self.history_loading, self.history_refresh_pending = False, False
        self.history_timer = QTimer(self)
        self.history_timer.setInterval(50)
        self.history_timer.timeout.connect(self.history_loaded)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        settings_actions = QHBoxLayout()
        self.app_settings = QPushButton('App settings…')
        self.app_settings.clicked.connect(self.edit_app_settings)
        settings_actions.addWidget(self.app_settings)
        settings_actions.addWidget(self.settings)
        layout.addLayout(settings_actions)
        layout.addWidget(self.action_footer)
        self.show_stage(0)
        for control in (self.configuration.operation, self.configuration.platform, self.configuration.backend):
            control.currentTextChanged.connect(self.invalidate)
        self.configuration.build_override.valueChanged.connect(self.invalidate)
        for control in (self.configuration.revision, self.configuration.pattern, self.configuration.release_tag):
            control.textChanged.connect(self.invalidate)
        self.refresh_operations()
        self.refresh_backends()
        self.refresh_suites()
        self.refresh_history()
        checks = next((name for name in ('Test', 'Check') if name in self.project.operations), None)
        if checks:
            self.configuration.operation.setCurrentText(checks)
        else:
            self.configuration.goal.setCurrentIndex(self.configuration.goal.findData('advanced'))
        self.configuration.update_summary()
        self.plan_feedback.setText('Select at least one platform above, then review your plan.'
            if self.configuration.platform_checks else 'Choose the checks or workflow you want, then review your plan.')
        self.status.clear()
        self.update_run_actions()


    # Compatibility handles for existing callers; configuration owns these widgets.
    @property
    def preset(self):
        return self.configuration.preset

    @property
    def operation(self):
        return self.configuration.operation

    @property
    def platform(self):
        return self.configuration.platform

    @property
    def backend(self):
        return self.configuration.backend

    @property
    def suite(self):
        return self.configuration.suite

    @property
    def revision(self):
        return self.configuration.revision

    @property
    def pattern(self):
        return self.configuration.pattern

    @property
    def build_override(self):
        return self.configuration.build_override

    @property
    def release_tag(self):
        return self.configuration.release_tag

    @property
    def run_controls(self):
        return self.configuration.run_controls

    @property
    def advanced_toggle(self):
        return self.configuration.advanced_toggle

    @property
    def goal(self):
        return self.configuration.goal

    @property
    def platform_checks(self):
        return self.configuration.platform_checks

    @property
    def platform_backends(self):
        return self.configuration.platform_backends

    @property
    def destination_checks(self):
        return self.configuration.destination_checks

    @property
    def readiness(self):
        return self.configuration.readiness

    @property
    def preset_note(self):
        return self.configuration.preset_note

    @property
    def run_fields(self):
        return self.configuration.run_fields

    def goal_changed(self, *_):
        if self.configuration.goal.currentData() == 'build':
            if self.configuration.operation.findText('Build') < 0:
                self.configuration.operation.addItem('Build')
            self.configuration.operation.setCurrentText('Build')
        if self.configuration.goal.currentData() == 'validate' and not self.configuration.platform_checks:
            checks = next((name for name in ('Test', 'Check') if name in self.project.operations), None)
            if checks:
                self.configuration.operation.setCurrentText(checks)
        self.invalidate(preserve_preset=True)

    def select_preset(self, name):
        choices=getattr(self.project,'workflow_presets',{}).get(name)
        self.preset_error = ''
        if not choices:
            return
        self.configuration.goal.setCurrentIndex(self.configuration.goal.findData('advanced'))
        self.configuration.preset_note.setText('Suggested workflow: ' + name + '. Changes will be marked Modified.')
        self.applying_preset = True
        try:
            if self.configuration.platform.findText(choices['platform']) < 0:
                raise ValueError('This workflow platform is unavailable in the selected project.')
            self.configuration.platform.setCurrentText(choices['platform'])
            operations = getattr(self.project, 'operations_for', lambda _: self.project.operations)(choices['platform'])
            if choices['operation'] not in operations:
                raise ValueError('This workflow operation is unavailable on the selected platform.')
            self.configuration.operation.setCurrentText(choices['operation'])
            if choices['backend'] not in self.project.backend_options(choices['platform'], choices['operation']):
                raise ValueError('This workflow backend is unavailable on this host. Choose a supported workflow or Custom operation.')
            self.configuration.backend.setCurrentText(choices['backend'])
            index = self.configuration.suite.findData(choices.get('suite', ''))
            if index < 0:
                raise ValueError('This workflow test suite is unavailable for the selected operation.')
            self.configuration.suite.setCurrentIndex(index)
            self.invalidate()
        except (KeyError, TypeError, ValueError) as error:
            self.invalidate()
            self.preset_error = str(error)
            self.status.setText(self.preset_error)
        finally:
            self.applying_preset = False
            self.selection_changed.emit(self.choices())

    def refresh_operations(self, *_):
        factory=getattr(self.project,'operations_for',None)
        if factory:
            previous=self.configuration.operation.currentText()
            options = tuple(factory(self.configuration.platform.currentText()))
            self.configuration.operation.clear(); self.configuration.operation.addItems(options)
            if previous:
                if previous not in options:
                    self.configuration.operation.addItem(previous)
                    self.configuration.operation.setItemData(self.configuration.operation.count()-1,
                        'Unavailable on this platform. Choose a supported operation explicitly.', 3)
                self.configuration.operation.setCurrentText(previous)

    def refresh_backends(self, *_):
        previous = self.configuration.backend.currentText()
        self.configuration.backend.clear()
        options = tuple(self.project.backend_options(self.configuration.platform.currentText(), self.configuration.operation.currentText()))
        self.configuration.backend.addItems(options)
        if previous:
            if previous not in options:
                self.configuration.backend.addItem(previous)
                self.configuration.backend.setItemData(self.configuration.backend.count()-1,
                    'Unavailable for this work. Choose an execution host explicitly.', 3)
            self.configuration.backend.setCurrentText(previous)

    def refresh_suites(self, *_):
        if not hasattr(self, 'suite'):
            return
        previous = self.configuration.suite.currentData()
        self.configuration.suite.blockSignals(True)
        self.configuration.suite.clear()
        self.configuration.suite.addItem('Full declared suite / operation default', '')
        for row in getattr(self.project, 'test_suites', []):
            if self.configuration.platform.currentText() in row['platforms'] and self.configuration.operation.currentText() in row['operations']:
                self.configuration.suite.addItem(row['label'] + ' · ' + row['tier'], row['id'])
                self.configuration.suite.setItemData(self.configuration.suite.count()-1, row.get('description', ''), 3)
        self.configuration.suite.setCurrentIndex(max(0, self.configuration.suite.findData(previous)))
        self.configuration.suite.blockSignals(False)

    @property
    def saved_presets(self):
        return self.preset_controller.picker

    @property
    def preset_actions(self):
        return self.preset_controller.actions

    @property
    def preset_menu(self):
        return self.preset_controller.menu_button

    def refresh_saved_presets(self):
        self.preset_controller.refresh()

    def restore_selection(self, choices):
        self.applying_preset = True
        try:
            self.configuration.restore_choices(choices)
        finally:
            self.applying_preset = False
        self.invalidate()
        self.stages.setCurrentIndex(0)

    def choices(self):
        return self.configuration.choices()

    def invalidate(self, *_, preserve_preset=False):
        self.selection_revision += 1
        self.plan = None
        self.start.setEnabled(False)
        self.stage_tabs.setTabEnabled(1, False)
        if hasattr(self, 'review_state'):
            self.review_state.setText('Choices or settings changed. Return to choices and prepare a fresh plan.')
        if not self.applying_preset and not preserve_preset:
            self.preset_error = ''
            if self.configuration.preset.currentIndex():
                self.configuration.preset_note.setText(self.configuration.preset.currentText() + ' · Modified. Review the updated plan before running.')
        if not self.applying_preset:
            self.selection_changed.emit(self.choices())
        if hasattr(self, 'status'):
            self.status.clear()
            self.plan_feedback.setText('Choices changed. Choose Next: review plan to check them before starting.')
            self.plan_feedback.hide()
            self.preparation_error_section.hide()
        if not self.applying_preset and self.configuration.platform_checks and self.configuration.goal.currentData() in {'validate', 'deliver'}:
            from .journeys import request
            try:
                request(self.project.journey_capability, self.configuration.goal.currentData(),
                    [name for name, control in self.configuration.platform_checks.items() if control.isChecked()],
                    [name for name, control in self.configuration.destination_checks.items() if control.isChecked()]
                    if self.configuration.goal.currentData() == 'deliver' else [])
            except ValueError as error:
                self.configuration.readiness.setText(str(error))

    def show_stage(self, index):
        if index == 1 and getattr(self, 'review_live_dirty', False):
            self.review_workspace.set_facts(self.run_view.live_facts())
            self.review_live_dirty = False
        self.stage_heading.setVisible(index not in (1, 2))
        self.stage_tabs.blockSignals(True)
        self.stage_tabs.setCurrentIndex(index)
        self.stage_tabs.blockSignals(False)
        if hasattr(self, 'footer_pages'):
            self.footer_pages.setCurrentIndex(index)
        self.stage_heading.setText((
            '<b>1 · Choose work</b> → 2 · Review plan → 3 · Run & results<br>Choose what you want to test and where to deliver it.',
            '1 · Choose work → <b>2 · Review plan</b> → 3 · Run & results<br>Check the source and destinations. Go back to change your choices.',
            '1 · Choose work → 2 · Review plan → <b>3 · Run & results</b><br>Follow progress, inspect test results and review any delivery approval.',
            '<b>History</b><br>Open a saved run to see its original results. Open another run with the + tab button.'
        )[index])

    def update_run_actions(self):
        if not hasattr(self, 'run_problems'):
            return
        review = self.continue_run.isEnabled() and not self.continue_run.isHidden()
        self.run_view.set_review_available(review)
        problems = self.run_view.has_problems()
        from .device_retry import candidates
        retry_phases = candidates(self.run_view.plan,
            dict(status=self.run_view.outcome, phases=list(self.run_view.facts.values()))) if self.run_view.plan else []
        retryable = bool(retry_phases)
        self.run_view.run_choices.flow.set_card_actions(
            {phase.id: 'Retry install' for phase in retry_phases} if not getattr(self, 'is_busy', False) else {})
        self.retry_device.setVisible(retryable)
        self.retry_device.setEnabled(retryable and not getattr(self, 'is_busy', False))
        self.run_problems.setVisible(problems)
        self.run_problems.setText(self.run_view.attention_problems.text())
        approval = review and (self.run_view.outcome == 'awaiting_review' or any(
            row.get('status') == 'awaiting_review' for row in self.run_view.facts.values()))
        primary = self.continue_run if approval else self.run_problems if problems else (
            self.continue_run if review else self.open_results)
        for button in (self.open_results, self.run_problems, self.continue_run):
            style_button(button, 'primary' if button is primary else 'secondary')

    def edit_app_settings(self):
        from .application_settings_ui import ApplicationSettingsDialog
        ApplicationSettingsDialog(self.project, self).exec()

    def edit_settings(self):
        try:
            dialog = SettingsDialog(self.project, self)
            if dialog.exec():
                self.invalidate()
                self.settings_saved.emit()
                self.preparation_message('Project settings saved. Review a fresh plan to use these values.')
        except Exception as error:
            self.status.setText('Could not open Settings: ' + self.redact(str(error)))

    def clean_builds(self):
        from .storage_ui import StorageDialog
        StorageDialog(self.project, self).exec()

    def inspect_plan(self):
        if self.preparing or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if hasattr(self.project, 'registry'):
            try:
                self.project.registry.resolve(self.project.key)
            except (OSError, ValueError, KeyError) as error:
                self.preparation_message('Could not open this project. ' + self.redact(str(error)))
                return
        if not self.configuration.revision.text().strip():
            self.configuration.open_section('source')
            self.preparation_message('Choose a source revision, or select Current files or Latest commit in Source. No plan has been prepared.')
            return
        if self.preset_error:
            self.preparation_message(self.preset_error)
            return
        if self.configuration.run_fields.missing_selection():
            row = self.configuration.run_fields.missing_selection_field()
            self.configuration.open_section('delivery', next(iter(row.get('destinations', [])), ''))
            self.preparation_message(self.configuration.run_fields.missing_selection())
            return
        from functools import partial
        from .preparation import preparation_request, validate_gui_selection
        selection = self.configuration.selection()
        integrated = bool(self.configuration.platform_checks) and selection.goal in {'validate', 'deliver'}
        try:
            validate_gui_selection(self.project, selection, integrated=integrated)
        except ValueError as error:
            self.preparation_message(str(error))
            if integrated:
                self.configuration.readiness.setText(str(error))
            return
        request = preparation_request(selection, integrated=integrated,
                                      include_backends=self.configuration.selectable_backends)
        prepare = partial(request.prepare, self.project)
        self.preparing_proposal = self.configuration.current_proposal
        self.invalidate(preserve_preset=True)
        self.preparation_revision = self.selection_revision
        self.preparing = True
        self.preparing_verification = False
        self.set_busy(True)
        self.session.current_phase = 'Inspecting source and prerequisites'
        self.session.phase_elapsed.start()
        self.show_elapsed()
        QThreadPool.globalInstance().start(PreparePlan(
            prepare, self.prepared))
        self.preparation_timer.start()

    def preparation_message(self, text, *, details=''):
        self.preparation_error.setPlainText(details)
        self.preparation_error_section.setVisible(bool(details))
        self.preparation_error_section.toggle.setChecked(bool(details))
        self.plan_feedback.show()
        self.status.setText(text)
        self.plan_feedback.setText(text)
        self.configuration.ensureWidgetVisible(self.plan_feedback)

    def plan_prepared(self):
        try:
            plan, error = self.prepared.get_nowait()
        except Empty:
            return
        self.preparation_timer.stop()
        device_retry = getattr(self, 'preparing_device_retry', False)
        self.preparing_device_retry = False
        self.preparing = False
        self.set_busy(False)
        if error is not None:
            message = str(error).strip().splitlines()
            self.preparation_message('Could not prepare the plan. ' + self.redact(message[-1] if message else 'Unknown error'),
                details=self.redact(getattr(error, 'details', str(error))))
            if 'committed' in error.lower() and ('source' in error.lower() or 'revision' in error.lower()):
                self.configuration.show_source_blocker()
                self.configuration.open_section('source')
                requirements = [message for message in self.configuration.current_proposal.messages if 'requires committed source' in message]
                self.configuration.source_summary.setText('\n'.join(requirements) if requirements else 'Choose Latest commit or a specific revision to use committed source.')
                self.configuration.source_summary.show()
            return
        if self.selection_revision != self.preparation_revision:
            self.preparation_message('Selection changed during preparation; inspect a fresh plan.')
            return
        from .workflows import start_authorized_effects, require_build_only
        if self.configuration.goal.currentData() == 'build':
            try:
                require_build_only(plan)
            except ValueError as error:
                self.plan = None
                self.preparation_message(str(error))
                return
        plan = start_authorized_effects(plan)
        self.plan = plan
        if not self.preparing_verification and self.configuration.goal.currentData() == 'validate':
            effects = [(phase.effect if phase.effect != 'inherit' else plan.effect) for phase in plan.phases]
            if any(effect in {'deploy', 'upload', 'publish'} for effect in effects) or 'test' not in effects:
                self.plan = None
                self.preparation_message('Validation needs a checks-only plan with test steps and no delivery actions. Choose Advanced operation for other work.')
                return
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in self.plan.secret_environment)
        self.present_plan(self.plan, proposal=self.preparing_proposal)
        self.stages.setCurrentIndex(1)
        self.start.setEnabled(True)
        effects = {phase.effect if phase.effect != 'inherit' else plan.effect for phase in plan.phases}
        self.start.setText('Start reviewed workflow' if plan.journey and plan.journey['goal'] == 'deliver'
                           else 'Start build' if self.configuration.goal.currentData() == 'build'
                           else 'Start validation' if self.configuration.goal.currentData() == 'validate'
                           else 'Start checks' if effects <= {'test', 'inspect'} else 'Start reviewed workflow')
        self.status.clear()
        if device_retry:
            self.run_plan()

    def verify_settings(self):
        if self.preparing or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.preparing_proposal = None
        self.invalidate(preserve_preset=True)
        self.preparation_revision = self.selection_revision
        self.preparing, self.preparing_verification = True, True
        self.set_busy(True)
        self.status.setText('Preparing connection checks. Review the plan before starting them.')
        QThreadPool.globalInstance().start(PreparePlan(self.project.verification_plan, self.prepared))
        self.preparation_timer.start()

    def run_plan(self):
        if self.plan is None or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        confirmed = self.plan.effect in {'deploy', 'upload', 'publish', 'dispatch'}
        separate_approval = any(phase.approval_required for phase in self.plan.phases
            if (phase.effect if phase.effect != 'inherit' else self.plan.effect) in {'deploy', 'upload', 'publish', 'dispatch'})
        if confirmed and separate_approval and QMessageBox.question(self, 'Confirm reviewed operation',
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
        self.seed_run(self.plan)
        self.open_results.setEnabled(False)
        self.continue_run.setEnabled(False)
        self.stages.setCurrentIndex(2)
        self.set_busy(True)
        self.status.setText('Queued…')
        self.session.launch(self.project.interpreter, path, run, confirmed=confirmed)

    def retry_device_install(self, step=None):
        from functools import partial
        from .device_retry import candidates, prepare
        from .history import load_run
        if getattr(self, 'is_busy', False) or not self.result:
            return
        try:
            plan, report = load_run(self.result)
            if plan.project != self.project.descriptor['name'] or (plan.adapter and
                    plan.adapter.get('checkout') != str(self.project.root)):
                raise ValueError('Choose a run from this registered project checkout.')
            phases = candidates(plan, report)
            if not phases:
                raise ValueError('No uncertain device installation is eligible for an explicit retry.')
            labels = [phase.id for phase in phases]
            if not isinstance(step, str) or not step:
                step, accepted = (labels[0], True) if len(labels) == 1 else QInputDialog.getItem(
                    self, 'Choose device installation', 'Retry only this installation:', labels, 0, False)
            else:
                accepted = step in labels
            if not accepted:
                return
            self.preparing_device_retry = True
            self.preparation_revision = self.selection_revision
            self.preparing_proposal = None
            self.preparing, self.preparing_verification = True, True
            self.set_busy(True)
            self.status.setText('Verifying the prepared app for a separate device retry…')
            QThreadPool.globalInstance().start(PreparePlan(partial(prepare, self.result.parent, step, authorized=True), self.prepared))
            self.preparation_timer.start()
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            self.status.setText(self.redact(str(error)))

    def resume_workflow(self, retained=None):
        from pathlib import Path
        if self.preparing or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if retained and not isinstance(retained, bool):
            path = str(retained)
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Select retained result.json', str(self.project.results_directory), 'JSON (*.json)')
        if not path:
            return
        from .review import VerifyContinuation
        descriptor = getattr(self.project, 'descriptor', {})
        self.review_job = VerifyContinuation(path, descriptor, getattr(self.project, 'root', ''),
                                              self.selection_revision, self.review_results)
        self.reviewing = True
        self.set_busy(True)
        self.status.setText('Verifying retained results and artifact checksums…')
        self.review_timer.start()
        QThreadPool.globalInstance().start(self.review_job)

    def continuation_verified(self):
        try:
            revision, continuation, error = self.review_results.get_nowait()
        except Empty:
            return
        self.review_timer.stop()
        self.reviewing = False
        self.set_busy(False)
        if self.closing or self.review_job.cancelled.is_set() or revision != self.selection_revision:
            self.status.setText('Review cancelled or selection changed; inspect the intended run again.')
            return
        if error is not None:
            self.status.setText(self.redact(error))
            return
        result, plan, previous, steps = (continuation.path, continuation.plan,
                                         continuation.report, continuation.steps)
        try:
            engine_change = getattr(continuation, 'engine_change', None)
            if engine_change is not None:
                answer = QMessageBox.question(self, 'Manager updated since this run',
                    'This saved run used a different manager or commonUtils revision. '
                    'Prepared artifacts and completed steps were verified and will be retained. '
                    'Continue unfinished steps with the versions below?\n\n' +
                    json.dumps(self.redacted_data(engine_change), indent=2),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self.present_plan(plan)
            self.seed_run(plan, previous['phases'])
            self.plan = None
            self.result = result
            self.start.setEnabled(False)
            self.open_results.setEnabled(True)
            self.run_view.set_output(self.redact(json.dumps(dict(plan=plan.data(), previous=previous), indent=2)))
            self.run_view.complete(previous)
            self.stages.setCurrentIndex(2)
            confirmed = bool(steps or plan.effect in {'deploy', 'upload', 'publish', 'dispatch'})
            selected = self.confirm_continuation(plan, previous, steps) if confirmed else True
            if not selected:
                return
            approvals = continuation.approvals
            if isinstance(selected, tuple):
                approvals = tuple(approval for approval in approvals if approval.step in selected)
            # The CLI verifies these exact identities again, after the dialog.
            self.plan, self.result = plan, result
            self.active_plan = plan
            self.seed_run(plan, [row for row in previous['phases'] if row['status'] == 'passed'])
            self.continue_run.setEnabled(False)
            self.stages.setCurrentIndex(2)
            self.set_busy(True)
            self.session.launch(self.project.interpreter, result.parent / 'plan.json', result.parent,
                                resume=True, confirmed=confirmed, approvals=approvals,
                                engine_review=engine_change['identity'] if engine_change else None)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            self.status.setText(self.redact(str(error)))

    def confirm_continuation(self, plan, previous, steps):
        from .run_ui import plan_overview
        previews = {}
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
                    try:
                        previews[artifact['path']] = json.loads(preview)
                    except ValueError:
                        pass
        from .approval_summary import approval_cards
        from .plan_summary import captured_choices
        safe = self.safe_plan(plan)
        cards = approval_cards(safe, self.redacted_data(previous), steps,
            self.redacted_data(getattr(self.project, 'run_fields', ())), previews)
        source = captured_choices(safe)[0][1]
        dialog = EffectReviewDialog('\n'.join(lines), self, steps=steps, cards=cards, source=source)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        return tuple(step for step, control in dialog.approvals.items() if control.isChecked()) if steps else True

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
        self.is_busy = busy
        self.session.set_busy(busy)
        self.stage_tabs.setEnabled(not busy)
        for control in (self.configuration.source_mode, self.view_run, self.new_run, self.past_runs, self.back, self.app_settings, self.prepare, self.start, self.settings, self.verify, self.cleanup, self.resume, self.configuration.operation,
                        self.configuration.platform, self.configuration.backend, self.configuration.preset, self.configuration.suite, self.configuration.revision, self.configuration.pattern, self.configuration.build_override, self.configuration.release_tag,
                        self.refresh_history_button, self.view_history_button, self.history, self.history_view.search, self.history_view.filter, self.continue_run,
                        self.configuration.goal, self.configuration.blocker_strip, *self.configuration.goal_buttons.values(), *self.configuration.platform_checks.values(), *self.configuration.platform_backends.values(), *self.configuration.destination_checks.values(), *self.configuration.run_controls.values(), *self.configuration.run_fields.controls.values()):
            control.setEnabled(not busy)
        if not busy:
            self.configuration.update_mode()
        self.view_run.setEnabled(not busy and self.run_view.plan is not None)
        self.cleanup.setEnabled(not busy and hasattr(self.project, 'storage_inventory'))
        self.start.setEnabled(not busy and self.plan is not None)
        self.continue_run.setEnabled(not busy and bool(getattr(self, 'resumable', False)))
        self.continue_run.setVisible(not busy and bool(getattr(self, 'resumable', False)))
        self.view_history_button.setEnabled(not busy and self.history.currentItem() is not None)
        self.cancel.setEnabled(busy and not self.preparing)
        self.cancel.setVisible(busy)
        if not busy:
            self.cancel.setText('Cancel active work')
        self.update_run_actions()
        self.busy_changed.emit(busy)

    def show_elapsed(self):
        self.run_view.tick()
        if self.review_workspace.plan is not None and self.stages.currentIndex() == 1:
            self.review_workspace.set_facts(self.run_view.live_facts())
        phase = self.session.phase_elapsed.elapsed()/1000 if self.session.phase_elapsed.isValid() else 0
        self.status.setText(f'{self.session.current_phase}; phase {phase:.0f}s; total {self.session.elapsed.elapsed()/1000:.0f}s')
        if self.preparing:
            self.plan_feedback.setText(f'Preparing your plan… {phase:.0f}s. Checking source and prerequisites; no tests have started.')

    def read_output(self):
        self.output_timer.stop()
        self.session.read_stdout()
        budget = QElapsedTimer()
        budget.start()
        processed = 0
        while self.session.events.has_line():
            if processed >= 128 or budget.elapsed() >= 8:
                self.output_timer.start(0)
                break
            event = self.session.events.take_event()
            processed += 1
            if event.get('type') == 'output':
                self.run_view.append_output(event.get('phase'), self.redact(event['text'].rstrip()))
            elif event.get('type') == 'waiting':
                from .resources import resource_label
                resource = event.get('resource', '')
                reason = ('Waiting for shared resource: ' + resource_label(resource)) if resource else event['reason']
                if event['phase'] == 'workflow':
                    self.status.setText(self.redact(reason))
                else:
                    self.session.current_phase = event['phase'] + ': ' + self.redact(reason)
                    self.update_phase(dict(id=event['phase'], status='waiting_resource',
                                           reason=self.redact(reason), resource=self.redact(resource)), defer=True)
            elif event.get('type') == 'phase':
                # A suite can emit several growing case inventories in one
                # read. Merge before redaction/model work, not merely before
                # painting the same data repeatedly on the GUI thread.
                previous_status = self.run_view.state.queue_event(event)
                if not self.live_update_timer.isActive():
                    self.live_update_timer.start()
                if event['status'] == 'running' and previous_status != 'running':
                    self.session.phase_elapsed.start()
                self.session.current_phase = event['id'] + ': ' + event['status']
            elif event.get('type') == 'error':
                self.session.failure = self.redact(event['error'])
                self.status.setText(self.redact(event['error']))

    def update_phase(self, event, *, defer=False):
        self.run_view.update_phase(self.redacted_data(event), refresh=not defer)
        self.phase_rows = self.run_view.rows
        if defer:
            self.review_live_dirty = True
            if not self.live_update_timer.isActive():
                self.live_update_timer.start()
        else:
            self.review_workspace.set_facts(self.run_view.facts)
            self.review_live_dirty = False

    def flush_live_updates(self):
        for event in self.run_view.state.drain_events():
            self.run_view.update_phase(self.redacted_data(event), refresh=False)
            self.review_live_dirty = True
        self.run_view.flush_updates()
        if self.stages.currentIndex() == 1 and self.review_live_dirty:
            self.review_workspace.set_facts(self.run_view.live_facts())
            self.review_live_dirty = False

    def redacted_data(self, value, _redactor=None):
        from .redaction import Redactor
        if _redactor is None:
            _redactor = Redactor(self.redact.secrets)
        # Filter values rather than JSON syntax: password-like values and PEM
        # blocks must never consume the surrounding serialization delimiters.
        if isinstance(value, str):
            _redactor.private_key = False
            return _redactor(value)
        if isinstance(value, dict):
            return {key: self.redacted_data(item, _redactor) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redacted_data(item, _redactor) for item in value]
        return value

    def safe_plan(self, plan):
        from types import SimpleNamespace
        data = self.redacted_data(plan.data())
        data.setdefault('journey', {})
        for phase in data['phases']:
            phase.setdefault('approval_required', True)
        data['phases'] = [SimpleNamespace(**phase) for phase in data['phases']]
        return SimpleNamespace(**data)

    def present_plan(self, plan, proposal=None):
        self.review_live_dirty = False
        self.stage_tabs.setTabEnabled(1, True)
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in plan.secret_environment)
        safe = self.safe_plan(plan)
        if proposal is not None:
            from dataclasses import asdict
            from .proposed_workflow import ProposedStep, ProposedWorkflow
            nodes = []
            for node in proposal.phases:
                data = self.redacted_data(asdict(node))
                data['dependencies'] = tuple(data['dependencies'])
                data['platforms'] = tuple(data['platforms'])
                nodes.append(ProposedStep(**data))
            self.card_proposals[plan.identity] = ProposedWorkflow(tuple(nodes))
            if len(self.card_proposals) > 8:
                self.card_proposals.pop(next(iter(self.card_proposals)))
        proposal = self.card_proposals.get(plan.identity)
        journey = getattr(safe, 'journey', {})
        platforms = ', '.join(journey.get('platforms', ())) or str(safe.adapter.get('platform') or safe.settings.get('platform', safe.source.get('platform', 'Not specified by this project')))
        destinations = '\n'.join('• ' + name + ': ' + row['identity'] + ' (requires: ' + ', '.join(row.get('platforms', list(journey.get('platforms', {})))) + ')' for name, row in journey.get('destinations', {}).items())
        captured = safe.source.get('commit') or safe.source.get('fingerprint')
        source = ('Commit ' if safe.source.get('commit') else 'Snapshot ') + str(captured)[:12] if captured else str(safe.source.get('revision', 'See technical details'))
        if safe.source.get('selection'):
            source = str(safe.source['selection']) + ' · ' + source
        if safe.source.get('dirty'):
            source = 'Working tree with uncommitted changes · ' + str(source)
        effects = [phase.effect if phase.effect != 'inherit' else safe.effect for phase in safe.phases]
        from .plan_summary import start_scope
        scope = start_scope(safe)
        counts = {effect: effects.count(effect) for effect in set(effects)}
        upload_label = ('uploads requiring review' if all(phase.approval_required for phase in safe.phases
            if (phase.effect if phase.effect != 'inherit' else safe.effect) == 'upload') else 'uploads')
        work = ' · '.join(f'{counts[effect]} {label}' for effect, label in
            (('test', 'check steps'), ('inspect', 'inspection steps'), ('build', 'build steps'),
             ('upload', upload_label), ('deploy', 'device deliveries'), ('publish', 'publication steps'), ('dispatch','GitHub test launches'))
            if counts.get(effect))
        self.review_summary.setText(f'Project: {safe.project}\nSource: {source}\nPlatforms: {platforms}\nRuns on: {safe.backend}\n\n'
            + ('Each destination waits for its selected checks.\nIndependent preparation branches can proceed as their checks pass.\n' + scope + '\n' + destinations
               if destinations else 'This plan will run the selected checks. No delivery is selected.' if safe.effect == 'test' and all(phase.effect not in {'upload', 'deploy', 'publish'} for phase in safe.phases)
               else f'Operation: {safe.operation}\nEffect: {safe.effect}. Review technical steps before starting.')
            + f'\n\n{len(safe.phases)} steps in total: {work}.'
            + '\nThese are individual execution steps supplied by the project adapter. '
              'A step can contain multiple test cases. Selecting cards or tasks does not run anything.')
        executions = journey.get('executions',{})
        if executions:
            self.review_summary.setText(self.review_summary.text()+'\n'+'\n'.join(
                target+': '+row['backend'] for target,row in executions.items()))
        if safe.source.get('release_tag'):
            self.review_summary.setText(self.review_summary.text()+'\nRelease identifier: '+safe.source['release_tag'])
        values = safe.source.get('effective_settings',{}).get('values',{})
        captured_inputs = safe.source.get('run_overrides',{})
        run_inputs = [field['label']+':\n'+str(values[field['id']]) for field in getattr(self.project,'run_fields',[])
            if field['id'] in values and field['id'] in captured_inputs]
        self.review_run_inputs.setPlainText('\n\n'.join(run_inputs))
        self.review_run_inputs.hide()
        self.review_flow_plan = safe
        self.review_context.setText(f'{safe.project} · {platforms} · {source}')
        self.review_workspace.reset(safe, getattr(self.project, 'run_fields', ()),
            capability=getattr(self.project, 'journey_capability', None), proposal=proposal,
            summary=self.review_summary.text(), inputs=self.review_run_inputs.toPlainText())
        self.start.setToolTip(scope)
        effects = {phase.effect if phase.effect != 'inherit' else safe.effect for phase in safe.phases}
        self.review_help.setText(scope if effects & {'upload', 'deploy', 'publish', 'dispatch'} else '')
        self.review_help.setVisible(bool(self.review_help.text()))
        self.review_state.setText('Ready to start · ' + str(len(safe.phases)) + ' execution steps · ' + safe.project)

    def inspect_review_phase(self, key):
        self.review_workspace.inspect_phase(key)

    def review_step(self, key):
        self.review_workspace.inspect_phase(key) if key else self.review_flow.select('')

    def seed_run(self, plan, previous=()):
        safe = self.safe_plan(plan)
        self.run_view.reset(safe, self.redacted_data(previous), fields=getattr(self.project, 'run_fields', ()), capability=getattr(self.project, 'journey_capability', None), proposal=self.card_proposals.get(plan.identity))
        workspace = self.run_view.run_choices
        if self.review_workspace.plan == safe:
            workspace.splitter.setSizes(self.review_workspace.splitter.sizes())
            workspace.sidebar_splitter.setSizes(self.review_workspace.sidebar_splitter.sizes())
            group = self.review_workspace.flow.selected
            if group:
                workspace.flow.open_group(group)
            if self.review_workspace.selected:
                workspace.inspect_phase(self.review_workspace.selected)
        self.phase_rows = self.run_view.rows
        self.run_view.phase_log_reader = self.read_phase_log
        workspace.log_reader = self.read_phase_log
        self.review_workspace.log_reader = self.read_phase_log
        self.review_workspace.set_facts(self.run_view.facts if previous else {})
        self.view_run.setEnabled(True)
        self.stage_tabs.setTabEnabled(2, True)

    def prepare_close(self):
        if getattr(self, 'is_busy', False):
            return False
        self.configuration.run_fields.stop()
        self.closing = True
        self.history_timer.stop()
        self.review_timer.stop()
        self.history_refresh_pending = False
        pending = False
        for job in (self.review_job, self.history_job):
            if job is not None:
                job.cancelled.set()
                pending |= not job.done.is_set()
        if pending:
            QTimer.singleShot(50, self.idle.emit)
        return not pending

    def closeEvent(self, event):
        if self.prepare_close():
            super().closeEvent(event)
        else:
            event.ignore()
            if self.closing:
                QTimer.singleShot(50, self.close)

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
        self.history_view.set_rows(self.redacted_data(rows))

    def history_selection_changed(self, *_):
        self.view_history_button.setEnabled(self.history.currentItem() is not None and not self.preparing
            and not self.reviewing and self.process.state() == QProcess.ProcessState.NotRunning)

    def open_history(self, item, column=0, *, in_tab=False):
        if item is None or self.preparing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not in_tab and getattr(self, 'history_in_tabs', False):
            self.retained_run_requested.emit(item)
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
            self.run_view.set_output(self.redact(json.dumps(report, indent=2)))
            self.resumable = report['status'] in {'awaiting_review', 'failed', 'cancelled', 'unknown'}
            self.continue_run.setEnabled(self.resumable)
            self.continue_run.setVisible(self.resumable)
            self.continue_run.setText('Review and start GitHub checks…' if report['status']=='awaiting_review' and any(
                row.get('effect')=='dispatch' and row['status']=='awaiting_review' for row in report['phases'])
                else 'Continue independent steps…' if report['status'] == 'unknown'
                else 'Review and continue delivery…' if report['status'] == 'awaiting_review' else 'Retry unfinished steps…')
            self.update_run_actions()
            self.open_results.setEnabled(True)
            self.stages.setCurrentIndex(2)
            self.status.setText(f'Viewing retained run: {report["status"]}. Resume separately to continue work.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText('Cannot read retained run: ' + self.redact(str(error)))

    def read_phase_log(self, key):
        from pathlib import Path
        if not self.result:
            return ''
        name = self.run_view.facts.get(key, {}).get('log')
        if not name:
            return ''
        if not isinstance(name, str):
            raise ValueError('Invalid step log reference.')
        root = self.result.parent.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Log must stay inside the retained run directory.')
        with path.open('rb') as stream:
            raw = stream.read(262145)
        text = self.redact(raw[:262144].decode('utf-8', errors='replace'))
        return text + ('\nPreview truncated; open the results folder for the complete log.' if len(raw) > 262144 else '')

    def read_errors(self):
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        text = self.redact(text)
        self.session.stderr = (self.session.stderr + text)[-16384:]
        self.run_view.append_output(None, text)

    def cancel_operation(self):
        if self.reviewing:
            self.review_job.cancelled.set()
            self.status.setText('Cancelling artifact verification…')
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.run_view.cancellation_requested()
            self.cancel.setText('Cancelling…')
            self.cancel.setEnabled(False)
            self.session.current_phase = 'Cancelling active work and running owned cleanup…'
            self.show_elapsed()
            # Windows console processes do not reliably receive QProcess's
            # WM_CLOSE. The CLI observes this owned marker and retains its
            # structured cancelled result while it stops the phase's job/tree.
            self.session.cancel()

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
        if '\n' in self.session.buffer:
            QTimer.singleShot(0, lambda: self.finished(code, exit_status))
            return
        self.live_update_timer.stop()
        self.flush_live_updates()
        self.read_errors()
        self.set_busy(False)
        status = 'failed'
        if self.session.buffer:
            self.run_view.append_output(None, self.redact(self.session.buffer))
            self.session.buffer = ''
        try:
            if exit_status == QProcess.ExitStatus.CrashExit:
                raise ValueError('The operation process crashed.')
            if self.session.failure is not None:
                raise ValueError(self.session.failure)
            if not self.result or not self.result.is_file():
                detail = self.session.stderr.strip().splitlines()
                raise ValueError('The operation did not produce a result report.' +
                    (' Startup error: ' + detail[-1] if detail else ''))
            from .history import read_report
            report = read_report(self.result)
            if getattr(self, 'active_plan', None) and report.get('plan_identity') != self.active_plan.identity:
                raise ValueError('The result report belongs to a different reviewed plan.')
            status = report['status']
            if status not in {'passed', 'failed', 'cancelled', 'awaiting_review', 'unknown'} or not isinstance(report['phases'], list):
                raise ValueError('The result report is incomplete or invalid.')
            self.run_view.append_output(None, self.redact(json.dumps(report, indent=2)))
            for phase in report['phases']:
                if not isinstance(phase, dict):
                    raise ValueError('Invalid result phase.')
                self.update_phase(phase)
                for artifact in phase.get('artifacts', []):
                    evidence = self.artifact_preview(artifact['path'])
                    if evidence:
                        self.run_view.append_output(None, evidence)
            self.run_view.complete(report)
            if code and status == 'passed':
                raise ValueError('A passing report disagrees with the operation exit code.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            status = 'failed'
            self.run_view.unverified(self.redact(str(error)))
            self.run_view.append_output(None, 'Result/evidence could not be verified: ' + self.redact(str(error)))
        self.open_results.setEnabled(bool(self.result and self.result.parent.is_dir()))
        self.resumable = status in {'awaiting_review', 'failed', 'cancelled', 'unknown'} and bool(self.result and self.result.is_file())
        self.continue_run.setEnabled(self.resumable)
        self.continue_run.setVisible(self.resumable)
        self.continue_run.setText('Review and start GitHub checks…' if status=='awaiting_review' and any(
            row.get('effect')=='dispatch' and row['status']=='awaiting_review' for row in self.run_view.facts.values())
            else 'Continue independent steps…' if status == 'unknown'
            else 'Review and continue delivery…' if status == 'awaiting_review' else 'Retry unfinished steps…')
        self.update_run_actions()
        self.refresh_history()
        next_action = ' Review and continue this run to approve prepared delivery.' if status == 'awaiting_review' else ''
        self.status.setText(f'{status}; exit {code}. Results: {self.result}' + next_action)
