"""Optional Qt presentation for an explicitly supplied project adapter."""
from .adapter_sdk import supports
import json
import os
from queue import Empty, Queue
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QElapsedTimer, QProcess, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QInputDialog,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QTreeWidget, QProgressBar,
    QTreeWidgetItem, QTabBar, QTabWidget, QStackedWidget, QSplitter, QSizePolicy, QFrame,
)
from .settings_ui import SettingsDialog
from .approval_ui import EffectReviewDialog
from .ui_components import style_button, style_dialog_buttons, ViewportStack, CurrentPageStack, HeadingLabel, WrappingLayout, install_font_refresh
from .preparation_ui import PreparePlan, PreparationFailure, ReadRetainedRun


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
        from PySide6.QtWidgets import QApplication
        install_font_refresh(QApplication.instance())
        self.project, self.plan, self.result = project, None, None
        self.preparing = False
        self.preparation_job = None
        self.preparation_state = 'idle'
        self.preparation_render = None
        self.prepared_display = None
        self.current_run_stage = 0
        self.close_requested = False
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
        self.stage_tabs.setExpanding(False)
        self.stage_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.stage_tabs.setAccessibleName('Current run steps')
        for title in ('Choose work', 'Review plan', 'Progress && results'):
            self.stage_tabs.addTab(title)
        self.stage_tabs.setTabEnabled(1, False)
        self.stage_tabs.setTabEnabled(2, False)
        navigation = QHBoxLayout()
        navigation.addWidget(self.stage_tabs)
        navigation.addStretch()
        self.current_run = QPushButton('Current run', self)
        self.current_run.clicked.connect(self.return_to_current_run)
        self.current_run.hide()
        navigation.addWidget(self.current_run)
        self.past_runs = QPushButton('Project History', self)
        self.past_runs.clicked.connect(lambda: self.stages.setCurrentIndex(3))
        navigation.addWidget(self.past_runs)
        layout.addLayout(navigation)
        # Keep action handles for callers that navigate programmatically.
        self.new_run = QPushButton('Choose work', self)
        self.view_run = QPushButton('Progress & results', self)
        for button, index in ((self.new_run, 0), (self.view_run, 2)):
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
        self.configuration.run_fields.defaults_loaded.connect(lambda: self.invalidate(persist=False))
        self.configuration.platform.currentTextChanged.connect(self.refresh_operations)
        self.configuration.platform.currentTextChanged.connect(self.refresh_backends)
        self.configuration.operation.currentTextChanged.connect(self.refresh_backends)
        self.configuration.suite.currentIndexChanged.connect(self.invalidate)
        self.configuration.platform.currentTextChanged.connect(self.refresh_suites)
        self.configuration.operation.currentTextChanged.connect(self.refresh_suites)
        for control in self.configuration.run_controls.values():
            control.toggled.connect(self.invalidate)
        self.prepare = QPushButton('Next: review plan', self)
        self.prepare.clicked.connect(self.request_plan_preparation)
        self.start = QPushButton('Run reviewed plan', self)
        self.start.setEnabled(False)
        self.start.clicked.connect(self.run_plan)
        self.cancel = QPushButton('Cancel operation', self)
        self.cancel.setEnabled(False)
        self.cancel.hide()
        self.cancel.clicked.connect(self.cancel_operation)
        self.settings = QPushButton('Project settings…', self)
        self.settings.clicked.connect(self.edit_settings)
        self.storage_button = QPushButton('Manage build storage…', self)
        self.storage_button.setEnabled(True)
        self.storage_button.setToolTip('Review project storage, clean owned outputs and retire superseded workflows.')
        self.storage_button.clicked.connect(self.open_storage_dialog)
        self.resume = QPushButton('Open saved result file…', self)
        self.resume.clicked.connect(self.resume_workflow)
        self.verify = QPushButton('Verify connections/settings', self)
        self.verify.clicked.connect(self.request_connection_check_plan)
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
        self.preparation_progress = QProgressBar()
        self.preparation_progress.setRange(0, 0)
        self.preparation_progress.setAccessibleName('Plan preparation in progress')
        self.preparation_progress.setMaximumHeight(10)
        self.preparation_progress.hide()
        configuration_layout.addWidget(self.preparation_progress)
        self.cancel_preparation = QPushButton('Cancel preparation')
        self.cancel_preparation.clicked.connect(self.cancel_operation)
        self.cancel_preparation.hide()
        configuration_layout.addWidget(self.cancel_preparation)
        self.verify.hide()
        self.storage_button.hide()
        self.prepare.setDefault(True)
        self.prepare.setToolTip('Check choices and prepare the plan. Tests start after the next review.')
        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(6, 4, 6, 4)
        review_layout.setSpacing(4)
        review_heading = HeadingLabel('Review your run')
        review_layout.addWidget(review_heading)
        self.review_state = QLabel('Prepare a plan to review your choices.')
        self.review_state.setWordWrap(True)
        self.review_state.setTextFormat(Qt.TextFormat.PlainText)
        review_layout.addWidget(self.review_state)
        from .review_ui import ReviewPlanView
        self.review_workspace = ReviewPlanView()
        self.review_workspace.rendering_finished.connect(self.review_rendered)
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
        self.run_view.flow.lazy_canvas = True
        self.run_view.actions_in_footer = True
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
        self.retained_delivery = QPushButton('Prepare delivery from saved run…', self)
        self.retained_delivery.setToolTip('Select a saved run, then choose new recipients and review a fresh plan using verified retained inputs.')
        self.retained_delivery.setVisible(supports(self.project, 'retained_delivery_plan'))
        self.retained_delivery.setEnabled(False)
        self.retained_delivery.clicked.connect(self.request_retained_delivery)
        self.run_problems = QPushButton('View problems', self)
        self.run_problems.clicked.connect(self.run_view.show_problems)
        self.run_view.review_requested.connect(self.continue_run.click)
        self.run_view.results_workspace.flow.card_action_requested.connect(self.retry_device_install)
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
                ((self.cancel,), (self.open_results, self.run_problems, self.retained_delivery, self.retry_device, self.continue_run)),
                ((self.refresh_history_button, self.resume), (self.view_history_button,))):
            page = QWidget()
            actions = WrappingLayout(page)
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
        self.retained_results = Queue()
        self.retained_job = None
        self.retained_timer = QTimer(self)
        self.retained_timer.setInterval(25)
        self.retained_timer.timeout.connect(self.retained_loaded)
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
        from .presets_ui import PresetController
        self.preset_controller = PresetController(None, None, self, lambda action, panel: action())


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
        self.applying_preset = True
        try:
            self.configuration.goal.setCurrentIndex(self.configuration.goal.findData('advanced'))
            if self.configuration.platform.findText(choices['platform']) < 0:
                raise ValueError('This workflow platform is unavailable in the selected project.')
            self.configuration.platform.setCurrentText(choices['platform'])
            operations = getattr(self.project, 'operations_for', lambda _: self.project.operations)(choices['platform'])
            if choices['operation'] not in operations:
                raise ValueError('This workflow operation is unavailable on the selected platform.')
            self.configuration.operation.setCurrentText(choices['operation'])
            if choices['backend'] not in self.project.backend_options(choices['platform'], choices['operation']):
                raise ValueError('This workflow backend is unavailable on this host. Choose a supported preset or Custom run.')
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
        return not self.preset_error

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

    def invalidate(self, *_, preserve_preset=False, persist=True):
        self.selection_revision += 1
        self.prepared_display = None
        job = self.preparation_job
        if job is not None:
            job.reason = 'superseded'
            job.cancelled.set()
            self.cancel_preparation.setEnabled(False)
            self.review_workspace.cancel_rendering()
            if self.preparation_render is not None:
                self.finish_preparation('superseded')
        self.plan = None
        self.start.setEnabled(False)
        self.stage_tabs.setTabEnabled(1, False)
        if hasattr(self, 'review_state'):
            self.review_state.setText('Choices or settings changed. Return to choices and prepare a fresh plan.')
        if persist and not self.applying_preset and not getattr(self, 'is_retained_view', False):
            self.selection_changed.emit(self.choices())
        if hasattr(self, 'status'):
            self.status.setText('Choices changed; stopping the previous preparation…' if self.preparing else '')
            self.plan_feedback.setText('Choices changed. Choose Next: review plan to check them before starting.')
            self.plan_feedback.hide()
            self.preparation_error_section.hide()
            if self.preparing:
                self.plan_feedback.setText('Choices changed. Waiting for the previous preparation to stop; then review the current choices.')
                self.plan_feedback.show()
        if not self.applying_preset and self.configuration.platform_checks and self.configuration.goal.currentData() in {'validate', 'deliver'}:
            from .journeys import build_journey_intent
            try:
                build_journey_intent(self.project.journey_capability, self.configuration.goal.currentData(),
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
        if index < 3:
            self.current_run_stage = index
            self.stage_tabs.setCurrentIndex(index)
        self.current_run.setVisible(index == 3 or bool(getattr(self, 'saved_run_origin', None)))
        self.past_runs.setEnabled(index != 3)
        self.stage_tabs.blockSignals(False)
        if hasattr(self, 'footer_pages'):
            self.footer_pages.setCurrentIndex(index)
        self.stage_heading.setText((
            '<b>Choose work</b><br>Choose source, platforms and destinations.',
            'Review captured source, work and destinations.',
            'Follow progress and inspect evidence.',
            '<b>Project History</b><br>Inspect past evidence in a separate tab. Current run returns to your draft or active run.'
        )[index])

    def return_to_current_run(self):
        origin = getattr(self, 'saved_run_origin', None)
        if origin is not None:
            origin()
        else:
            index = self.current_run_stage
            self.stages.setCurrentIndex(index if self.stage_tabs.isTabEnabled(index) else 0)

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
        self.run_view.results_workspace.flow.set_card_actions(
            {phase.id: 'Retry install' for phase in retry_phases} if not getattr(self, 'is_busy', False) else {})
        self.retry_device.setVisible(retryable)
        self.retry_device.setEnabled(retryable and not getattr(self, 'is_busy', False))
        self.retained_delivery.setEnabled(bool(self.result) and not getattr(self, 'is_busy', False))
        self.run_problems.setVisible(problems)
        self.run_problems.setText(self.run_view.attention_problems.text())
        approval = review and (self.run_view.outcome == 'awaiting_review' or any(
            row.get('status') == 'awaiting_review' for row in self.run_view.facts.values()))
        unknown = self.run_view.outcome == 'unknown' or any(row.get('status') == 'unknown' for row in self.run_view.facts.values())
        primary = self.run_problems if unknown else self.continue_run if approval else self.run_problems if problems else (
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
                self.invalidate(persist=False)
                self.settings_saved.emit()
                self.preparation_message('Project settings saved. Review a fresh plan to use these values.')
        except Exception as error:
            self.status.setText('Could not open Settings: ' + self.redact(str(error)))

    def open_storage_dialog(self):
        from .storage_ui import StorageDialog
        StorageDialog(self.project, self).exec()

    def request_plan_preparation(self):
        if (self.closing or self.close_requested or self.preparing or self.reviewing or getattr(self, 'is_retained_view', False)
                or self.process.state() != QProcess.ProcessState.NotRunning):
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
        from .preparation import preparation_request, validate_gui_selection
        selection = self.configuration.selection()
        integrated = bool(self.configuration.platform_checks) and selection.goal in {'validate', 'deliver'}
        request = preparation_request(selection, integrated=integrated,
                                      include_backends=self.configuration.selectable_backends)
        project = self.project
        def prepare(cancelled, progress):
            progress('Checking project registration and selected work')
            if hasattr(project, 'registry'):
                project.registry.resolve(project.key)
            if cancelled():
                raise ValueError('Plan preparation cancelled.')
            validate_gui_selection(project, selection, integrated=integrated)
            source = {'working-tree': 'Current files', 'HEAD': 'Latest commit'}.get(selection.revision, selection.revision)
            progress('Waiting for the project to prepare source and prerequisites · ' + source)
            return request.prepare(project, cancelled=cancelled)
        self.begin_preparation(prepare, goal=selection.goal, proposal=self.configuration.current_proposal)

    def begin_preparation(self, prepare, *, goal='advanced', proposal=None,
                          verification=False, retained_delivery=False, device_retry=False):
        if self.closing or self.close_requested:
            return
        from copy import deepcopy
        from .review_presentation import prepare_review_data
        from .workflows import apply_start_review_policy, require_build_only
        fields = deepcopy(getattr(self.project, 'run_fields', ()))
        capability = deepcopy(getattr(self.project, 'journey_capability', None))
        proposal = deepcopy(proposal)
        def transform(plan):
            if not retained_delivery and goal == 'build':
                require_build_only(plan)
            plan = apply_start_review_policy(plan)
            if not verification and goal == 'validate':
                effects = {phase.effect if phase.effect != 'inherit' else plan.effect for phase in plan.phases}
                if effects & {'deploy', 'upload', 'publish'} or 'test' not in effects:
                    raise ValueError('Validation needs a checks-only plan with test steps and no delivery actions. Choose Project operation for other work.')
            return plan, prepare_review_data(plan, fields=fields, capability=capability, proposal=proposal)
        # Invalidation for a new request is not a changed user selection and
        # must not perform another remembered-choice disk write.
        self.plan = None
        self.start.setEnabled(False)
        self.stage_tabs.setTabEnabled(1, False)
        self.review_workspace.cancel_rendering()
        self.preparation_revision = self.selection_revision
        job = PreparePlan(lambda: prepare(job.cancelled.is_set, job.report), self.prepared, transform=transform)
        job.revision, job.request_id = self.selection_revision, uuid4().hex
        job.goal, job.proposal = goal, proposal
        job.device_retry, job.retained_delivery = device_retry, retained_delivery
        self.preparation_job = job
        self.preparing_proposal = proposal
        self.preparing_verification = verification
        self.preparing = True
        self.preparation_state = 'preparing'
        self.set_busy(True)
        self.session.current_phase = 'Checking project registration and selected work'
        self.session.phase_elapsed.start()
        self.preparation_error_section.hide()
        self.plan_feedback.show()
        self.preparation_progress.show()
        self.cancel_preparation.show()
        self.cancel_preparation.setEnabled(True)
        self.show_elapsed()
        QThreadPool.globalInstance().start(job)
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
        job = self.preparation_job
        if job is not None:
            while not job.progress.empty():
                message = job.progress.get_nowait()
                if not job.cancelled.is_set():
                    self.session.current_phase = message
                    self.show_elapsed()
        try:
            result = self.prepared.get_nowait()
        except Empty:
            return
        if result.job is not job:
            return
        self.preparation_timer.stop()
        if self.closing or job.cancelled.is_set() or job.revision != self.selection_revision:
            reason = job.reason or ('closed' if self.closing else 'superseded')
            self.finish_preparation(reason)
            return
        if result.error is not None:
            error = result.error
            self.finish_preparation('failed')
            message = str(error).strip().splitlines()
            self.preparation_message('Could not prepare the plan. ' + self.redact(message[-1] if message else 'Unknown error'),
                details=self.redact(getattr(error, 'details', str(error))))
            if 'committed' in error.lower() and ('source' in error.lower() or 'revision' in error.lower()):
                self.configuration.show_source_blocker()
                self.configuration.open_section('source')
                requirements = [text for text in self.configuration.current_proposal.messages
                                if 'requires committed source' in text]
                self.configuration.source_summary.setText('\n'.join(requirements) if requirements else
                    'Choose Latest commit or a specific revision to use committed source.')
                self.configuration.source_summary.show()
            return
        self.plan = result.plan
        self.prepared_display = (result.plan, result.review)
        self.preparation_render = result
        self.preparation_state = 'rendering'
        self.session.current_phase = 'Building the review · no work has started'
        self.show_elapsed()
        self.present_plan(self.plan, proposal=job.proposal, prepared=result.review)
        # Navigation away is safe. Do not pull someone out of project History.
        if self.stages.currentIndex() != 3:
            self.stages.setCurrentIndex(1)
        if not self.review_workspace.rendering:
            self.review_rendered()

    def review_rendered(self):
        result = self.preparation_render
        if result is None:
            return
        job = result.job
        if self.closing or job.cancelled.is_set() or job.revision != self.selection_revision:
            self.plan = None
            self.finish_preparation(job.reason or 'superseded')
            return
        plan = result.plan
        effects = {phase.effect if phase.effect != 'inherit' else plan.effect for phase in plan.phases}
        self.start.setText('Start reviewed workflow' if job.retained_delivery or plan.journey and plan.journey['goal'] == 'deliver'
                           else 'Start build' if job.goal == 'build'
                           else 'Start validation' if job.goal == 'validate'
                           else 'Start checks' if effects <= {'test', 'inspect'} else 'Start reviewed workflow')
        retry = job.device_retry
        self.finish_preparation('ready')
        self.start.setEnabled(True)
        self.review_state.setText('Ready to start · ' + str(len(plan.phases)) + ' execution steps · ' + plan.project)
        if retry:
            self.run_plan()

    def finish_preparation(self, state):
        self.preparation_state = state
        self.preparation_job = self.preparation_render = None
        self.preparing = False
        self.preparation_timer.stop()
        self.preparation_progress.hide()
        self.cancel_preparation.hide()
        self.set_busy(False)
        messages = {
            'ready': 'Plan ready to review. No checks, builds or delivery have started.',
            'cancelled': 'Preparation cancelled. Your choices are retained; review again when ready.',
            'superseded': 'Choices or settings changed during preparation. Review a fresh plan for the current choices.',
            'failed': 'Plan preparation failed. Your choices are retained.',
            'closed': 'Preparation stopped; closing.',
        }
        if state != 'ready':
            self.plan = None
            self.start.setEnabled(False)
            self.stage_tabs.setTabEnabled(1, False)
        self.preparation_message(messages.get(state, state))
        if self.closing:
            self.idle.emit()

    def request_connection_check_plan(self):
        if (self.closing or self.close_requested or getattr(self, 'is_retained_view', False) or self.retained_job is not None
                or self.preparing or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning):
            return
        from .preparation import cancellable_project
        project = self.project
        self.begin_preparation(lambda cancelled, progress: cancellable_project(project, cancelled).verification_plan(),
                               verification=True)

    def run_plan(self):
        if self.plan is None or self.preparing or self.reviewing or self.closing or self.close_requested or self.process.state() != QProcess.ProcessState.NotRunning:
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
        self.initialize_results_workspace(self.plan)
        self.open_results.setEnabled(False)
        self.continue_run.setEnabled(False)
        self.stages.setCurrentIndex(2)
        self.set_busy(True)
        self.status.setText('Queued…')
        self.session.launch(self.project.interpreter, path, run, confirmed=confirmed)

    def retry_device_install(self, step=None):
        from .device_retry import candidates, prepare
        from .history import load_run
        if self.closing or self.close_requested or getattr(self, 'is_busy', False) or not self.result:
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
            directory = self.result.parent
            self.begin_preparation(lambda cancelled, progress: prepare(directory, step, authorized=True),
                                   verification=True, device_retry=True)
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            self.status.setText(self.redact(str(error)))

    def request_retained_delivery(self):
        from .retained_delivery import prepare
        from .retained_delivery_ui import RetainedDeliveryDialog
        if self.closing or self.close_requested or getattr(self, 'is_busy', False) or not self.result:
            return
        if not supports(self.project, 'retained_delivery_plan'):
            self.status.setText('This project does not offer delivery from a saved run.')
            return
        directory = self.result.parent
        dialog = RetainedDeliveryDialog(self.project, directory, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        choices = dialog.choices(); dialog.deleteLater()
        from .preparation import cancellable_project
        project = self.project
        self.begin_preparation(lambda cancelled, progress: prepare(cancellable_project(project, cancelled), directory, **choices),
                               verification=True, retained_delivery=True)

    def resume_workflow(self, retained=None):
        from pathlib import Path
        if self.closing or self.close_requested or self.preparing or self.reviewing or self.retained_job is not None or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if retained and not isinstance(retained, bool):
            path = str(retained)
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Select retained result.json', str(self.project.results_directory), 'JSON (*.json)')
        if not path:
            return
        from .continuation_review_ui import VerifyContinuationTask
        descriptor = getattr(self.project, 'descriptor', {})
        self.review_job = VerifyContinuationTask(path, descriptor, getattr(self.project, 'root', ''),
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
        if self.closing or self.close_requested or self.review_job.cancelled.is_set() or revision != self.selection_revision:
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
                versions = []
                for name, identity in (('Previous', engine_change['previous']), ('Current', engine_change['current'])):
                    versions.append(name + ':')
                    for dependency in ('manager', 'commonUtils'):
                        value = identity.get(dependency, {})
                        versions.append('  ' + dependency + ' · ' + str(value.get('commit') or 'installed version')[:16]
                            + (' · local edits' if value.get('dirty') else ''))
                box = QMessageBox(QMessageBox.Icon.Question, 'Manager updated since this run',
                    'This saved run used a different manager or commonUtils revision. '
                    'Prepared artifacts and completed steps were verified and will be retained. '
                    'Continue unfinished steps with the current versions?\n\n' + '\n'.join(versions),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    self)
                box.setDetailedText(json.dumps(self.redacted_data(engine_change), indent=2))
                box.setDefaultButton(QMessageBox.StandardButton.No)
                if box.exec() != QMessageBox.StandardButton.Yes:
                    return
            self.present_plan(plan)
            self.initialize_results_workspace(plan, previous['phases'])
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
            from .continuation_actions import ContinuationSelection
            retry_options = {}
            if isinstance(selected, ContinuationSelection):
                if selected.steps is not None:
                    approvals = tuple(approval for approval in approvals if approval.step in selected.steps)
                retry_options['retry_failed'] = selected.retry_failed
            elif isinstance(selected, tuple):
                approvals = tuple(approval for approval in approvals if approval.step in selected)
            # The CLI verifies these exact identities again, after the dialog.
            self.plan, self.result = plan, result
            self.active_plan = plan
            self.initialize_results_workspace(plan, [row for row in previous['phases'] if row['status'] == 'passed'])
            self.continue_run.setEnabled(False)
            self.stages.setCurrentIndex(2)
            self.set_busy(True)
            self.session.launch(self.project.interpreter, result.parent / 'plan.json', result.parent,
                                resume=True, confirmed=confirmed, approvals=approvals,
                                engine_review=engine_change['identity'] if engine_change else None, **retry_options)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            self.status.setText(self.redact(str(error)))

    def confirm_continuation(self, plan, previous, steps):
        from .run_ui import plan_overview
        previews = {}
        lines = [plan_overview(self.redacted_plan_view(plan)), '', 'Steps awaiting approval: ' + ', '.join(steps),
                 '', 'Retained prerequisite results and evidence:']
        for row in self.redacted_data(previous['phases']):
            lines.append(row['id'] + ': ' + row['status'])
            for artifact in row.get('artifacts', []):
                lines += [f'  {artifact.get("kind", "file")}: {artifact["path"]}',
                          '  Original: ' + artifact.get('original_path', artifact['path']),
                          '  SHA-256: ' + artifact['sha256']]
                preview = self.read_json_evidence_preview(artifact['path'])
                if preview:
                    lines += ['  Prepared identity / evidence:', preview]
                    try:
                        previews[artifact['path']] = json.loads(preview)
                    except ValueError:
                        pass
        from .approval_summary import approval_cards
        from .plan_summary import captured_choices
        plan_view = self.redacted_plan_view(plan)
        cards = approval_cards(plan_view, self.redacted_data(previous), steps,
            self.redacted_data(getattr(self.project, 'run_fields', ())), previews)
        source = captured_choices(plan_view)[0][1]
        failed = any(row['status'] in {'failed', 'skipped', 'cancelled', 'timeout', 'interrupted'}
                     for row in previous['phases'])
        dialog = EffectReviewDialog('\n'.join(lines), self, steps=steps, cards=cards, source=source,
                                    retry_failed=not bool(steps) if failed else None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        selected = tuple(step for step, control in dialog.approvals.items() if control.isChecked()) if steps else None
        if dialog.retry_failed is not None:
            from .continuation_actions import ContinuationSelection
            return ContinuationSelection(selected, dialog.retry_failed.isChecked())
        return selected if steps else True

    def read_json_evidence_preview(self, path):
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
        editable = not busy or bool(self.preparing and not self.preparing_verification and not self.closing)
        for control in (self.configuration.source_mode, self.configuration.operation,
                        self.configuration.platform, self.configuration.backend, self.configuration.preset,
                        self.configuration.suite, self.configuration.revision, self.configuration.pattern,
                        self.configuration.build_override, self.configuration.release_tag, self.configuration.goal,
                        self.configuration.blocker_strip, *self.configuration.goal_buttons.values(),
                        *self.configuration.platform_checks.values(), *self.configuration.platform_backends.values(),
                        *self.configuration.destination_checks.values(), *self.configuration.run_controls.values(),
                        *self.configuration.run_fields.controls.values()):
            control.setEnabled(editable)
        for control in (self.app_settings, self.settings, self.verify, self.storage_button,
                        self.resume, self.prepare, self.start, self.continue_run):
            control.setEnabled(not busy)
        # Browsing does not authorize execution or mutate the selected checkout.
        self.stage_tabs.setEnabled(True)
        self.new_run.setEnabled(True)
        self.back.setEnabled(True)
        self.past_runs.setEnabled(self.stages.currentIndex() != 3)
        self.view_run.setEnabled(self.run_view.plan is not None)
        self.refresh_history_button.setEnabled(True)
        self.history.setEnabled(True)
        self.history_view.search.setEnabled(True)
        self.history_view.filter.setEnabled(True)
        self.history_selection_changed()
        if not busy:
            self.configuration.update_mode()
        self.start.setEnabled(not busy and self.plan is not None)
        self.continue_run.setEnabled(not busy and bool(getattr(self, 'resumable', False)))
        self.continue_run.setVisible(not busy and bool(getattr(self, 'resumable', False)))
        self.cancel.setEnabled(busy and not (self.preparation_job and self.preparation_job.cancelled.is_set()))
        self.cancel.setVisible(busy)
        self.cancel.setText('Cancel preparation' if self.preparing else 'Cancel active work')
        if getattr(self, 'is_retained_view', False):
            self.configuration.setEnabled(False)
            self.prepare.setEnabled(False)
            self.stage_tabs.setTabEnabled(0, False)
        self.update_run_actions()
        self.busy_changed.emit(busy)

    def show_elapsed(self):
        if self.preparing:
            seconds = self.session.phase_elapsed.elapsed() / 1000 if self.session.phase_elapsed.isValid() else 0
            job = self.preparation_job
            if job and job.cancelled.is_set():
                phase = ('Choices changed; stopping previous preparation' if job.reason == 'superseded'
                         else 'Cancellation requested; waiting for preparation cleanup')
            else:
                phase = self.session.current_phase
            text = f'{phase} · {seconds:.0f}s. No checks, builds or delivery have started.'
            self.status.setText(text)
            self.plan_feedback.setText(text)
            return
        self.run_view.tick()
        if self.review_workspace.plan is not None and self.stages.currentIndex() == 1:
            self.review_workspace.set_facts(self.run_view.live_facts())
        phase = self.session.phase_elapsed.elapsed()/1000 if self.session.phase_elapsed.isValid() else 0
        self.status.setText(f'{self.session.current_phase}; phase {phase:.0f}s; total {self.session.elapsed.elapsed()/1000:.0f}s')

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

    def redacted_plan_view(self, plan):
        from types import SimpleNamespace
        data = self.redacted_data(plan.data())
        data.setdefault('journey', {})
        for phase in data['phases']:
            phase.setdefault('approval_required', True)
        data['phases'] = [SimpleNamespace(**phase) for phase in data['phases']]
        return SimpleNamespace(**data)

    def present_plan(self, plan, proposal=None, *, prepared=None):
        self.review_live_dirty = False
        self.stage_tabs.setTabEnabled(1, True)
        from .redaction import Redactor
        self.redact = Redactor(os.environ.get(name) for name in plan.secret_environment)
        plan_view = prepared.plan if prepared is not None else self.redacted_plan_view(plan)
        if prepared is not None:
            proposal = prepared.proposal
            self.card_proposals[prepared.identity] = proposal
        if proposal is not None and prepared is None:
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
        proposal = self.card_proposals.get(prepared.identity if prepared is not None else plan.identity)
        journey = getattr(plan_view, 'journey', {})
        platforms = ', '.join(journey.get('platforms', ())) or str(plan_view.adapter.get('platform') or plan_view.settings.get('platform', plan_view.source.get('platform', 'Not specified by this project')))
        destinations = '\n'.join('• ' + name + ': ' + row['identity'] + ' (requires: ' + ', '.join(row.get('platforms', list(journey.get('platforms', {})))) + ')' for name, row in journey.get('destinations', {}).items())
        captured = plan_view.source.get('commit') or plan_view.source.get('fingerprint')
        source = ('Commit ' if plan_view.source.get('commit') else 'Snapshot ') + str(captured)[:12] if captured else str(plan_view.source.get('revision', 'See technical details'))
        if plan_view.source.get('selection'):
            source = str(plan_view.source['selection']) + ' · ' + source
        if plan_view.source.get('dirty'):
            source = 'Working tree with uncommitted changes · ' + str(source)
        effects = [phase.effect if phase.effect != 'inherit' else plan_view.effect for phase in plan_view.phases]
        from .plan_summary import describe_start_behavior
        scope = describe_start_behavior(plan_view)
        counts = {effect: effects.count(effect) for effect in set(effects)}
        upload_label = ('uploads requiring review' if all(phase.approval_required for phase in plan_view.phases
            if (phase.effect if phase.effect != 'inherit' else plan_view.effect) == 'upload') else 'uploads')
        work = ' · '.join(f'{counts[effect]} {label}' for effect, label in
            (('test', 'check steps'), ('inspect', 'inspection steps'), ('build', 'build steps'),
             ('upload', upload_label), ('deploy', 'device deliveries'), ('publish', 'publication steps'), ('dispatch','GitHub test launches'))
            if counts.get(effect))
        self.review_summary.setText(f'Project: {plan_view.project}\nSource: {source}\nPlatforms: {platforms}\nRuns on: {plan_view.backend}\n\n'
            + ('Each destination waits for its selected checks.\nIndependent preparation branches can proceed as their checks pass.\n' + scope + '\n' + destinations
               if destinations else 'This plan will run the selected checks. No delivery is selected.' if plan_view.effect == 'test' and all(phase.effect not in {'upload', 'deploy', 'publish'} for phase in plan_view.phases)
               else f'Operation: {plan_view.operation}\nEffect: {plan_view.effect}. Review technical steps before starting.')
            + f'\n\n{len(plan_view.phases)} steps in total: {work}.'
            + '\nThese are individual execution steps supplied by the project adapter. '
              'A step can contain multiple test cases. Selecting cards or tasks does not run anything.')
        executions = journey.get('executions',{})
        if executions:
            self.review_summary.setText(self.review_summary.text()+'\n'+'\n'.join(
                target+': '+row['backend'] for target,row in executions.items()))
        if plan_view.source.get('release_tag'):
            self.review_summary.setText(self.review_summary.text()+'\nRelease identifier: '+plan_view.source['release_tag'])
        values = plan_view.source.get('effective_settings',{}).get('values',{})
        captured_inputs = plan_view.source.get('run_overrides',{})
        run_inputs = [field['label']+':\n'+str(values[field['id']]) for field in getattr(self.project,'run_fields',[])
            if field['id'] in values and field['id'] in captured_inputs]
        self.review_run_inputs.setPlainText('\n\n'.join(run_inputs))
        self.review_run_inputs.hide()
        self.review_flow_plan = plan_view
        self.review_context.setText(f'{plan_view.project} · {platforms} · {source}')
        self.review_workspace.reset(plan_view, getattr(self.project, 'run_fields', ()),
            capability=getattr(self.project, 'journey_capability', None), proposal=proposal,
            summary=self.review_summary.text(), inputs=self.review_run_inputs.toPlainText(), prepared=prepared)
        self.start.setToolTip(scope)
        effects = {phase.effect if phase.effect != 'inherit' else plan_view.effect for phase in plan_view.phases}
        self.review_help.setText(scope)
        self.review_help.setVisible(bool(self.review_help.text()))
        self.review_state.setText(('Building the review · ' if self.preparing else 'Ready to start · ') + str(len(plan_view.phases)) + ' execution steps · ' + plan_view.project)

    def inspect_review_phase(self, key):
        self.review_workspace.inspect_phase(key)

    def review_step(self, key):
        self.review_workspace.inspect_phase(key) if key else self.review_flow.select('')

    def initialize_results_workspace(self, plan, previous=(), *, prepared=None):
        if prepared is None and self.prepared_display is not None and self.prepared_display[0] is plan:
            prepared = self.prepared_display[1]
        plan_view = prepared.plan if prepared is not None else self.redacted_plan_view(plan)
        if prepared is not None:
            self.run_view.results_workspace.stage_prepared(prepared)
        identity = prepared.identity if prepared is not None else plan.identity
        self.run_view.reset(plan_view, self.redacted_data(previous), fields=getattr(self.project, 'run_fields', ()), capability=getattr(self.project, 'journey_capability', None), proposal=self.card_proposals.get(identity))
        workspace = self.run_view.results_workspace
        if self.review_workspace.plan == plan_view:
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
        if self.preparing:
            self.closing = True
            self.cancel_operation()
            if self.preparing:
                return False
        if getattr(self, 'is_busy', False):
            return False
        self.review_workspace.cancel_rendering()
        self.run_view.results_workspace.cancel_rendering()
        self.configuration.run_fields.stop()
        self.closing = True
        self.history_timer.stop()
        self.review_timer.stop()
        self.retained_timer.stop()
        self.history_refresh_pending = False
        pending = False
        for job in (self.review_job, self.history_job, self.retained_job):
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
        can_view = getattr(self, 'history_in_tabs', False) or not getattr(self, 'is_busy', False)
        self.view_history_button.setEnabled(self.history.currentItem() is not None and can_view)

    def open_history(self, item, column=0, *, in_tab=False):
        if item is None or self.closing:
            return
        if not in_tab and getattr(self, 'history_in_tabs', False):
            self.retained_run_requested.emit(item)
            return
        if self.preparing or self.reviewing or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        from pathlib import Path
        if self.retained_job is not None:
            return
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        self.is_retained_view = True
        self.plan = None
        self.start.setEnabled(False)
        self.stage_tabs.setTabEnabled(1, False)
        self.configuration.setEnabled(False)
        self.prepare.setEnabled(False)
        self.stage_tabs.setTabEnabled(0, False)
        self.status.setText('Reading saved evidence… The current run remains in its own tab.')
        from copy import deepcopy
        self.retained_job = ReadRetainedRun(path, self.retained_results,
            fields=deepcopy(getattr(self.project, 'run_fields', ())),
            capability=deepcopy(getattr(self.project, 'journey_capability', None)))
        self.retained_timer.start()
        QThreadPool.globalInstance().start(self.retained_job)

    def retained_loaded(self):
        try:
            job, plan, report, error = self.retained_results.get_nowait()
        except Empty:
            return
        if job is not self.retained_job:
            return
        self.retained_job = None
        self.retained_timer.stop()
        if self.closing or job.cancelled.is_set():
            self.idle.emit()
            return
        if error is not None:
            self.status.setText('Cannot read retained run: ' + self.redact(error))
            return
        try:
            path = job.path
            self.plan = None
            self.start.setEnabled(False)
            self.result = path
            self.present_plan(plan, prepared=job.review)
            self.initialize_results_workspace(plan, report['phases'], prepared=job.review)
            self.run_view.complete(report)
            self.run_view.saved_context.setText('Saved run · ' + path.parent.name +
                (' · ' + str(report['started_at']) if report.get('started_at') else ''))
            self.run_view.saved_context.setToolTip('Original engine identity:\n' +
                self.redact(json.dumps(report.get('engine', {}), indent=2)))
            self.run_view.saved_context.show()
            self.run_view.set_output(self.redact(json.dumps(report, indent=2)))
            self.resumable = not report.get('retirement') and report['status'] in {'awaiting_review', 'failed', 'cancelled', 'unknown'}
            self.continue_run.setEnabled(self.resumable)
            self.continue_run.setVisible(self.resumable)
            from .continuation_actions import continuation_label
            self.continue_run.setText(continuation_label(report))
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
        if self.preparing and self.preparation_job is not None:
            job = self.preparation_job
            job.reason = 'closed' if self.closing or self.close_requested else 'cancelled'
            job.cancelled.set()
            self.preparation_state = 'cancelling'
            self.cancel_preparation.setEnabled(False)
            self.cancel.setEnabled(False)
            self.review_workspace.cancel_rendering()
            self.show_elapsed()
            if self.preparation_render is not None:
                self.plan = None
                self.finish_preparation(job.reason)
            return
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
                    evidence = self.read_json_evidence_preview(artifact['path'])
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
        from .continuation_actions import continuation_label
        self.continue_run.setText(continuation_label(dict(status=status, phases=list(self.run_view.facts.values()))))
        self.update_run_actions()
        self.refresh_history()
        next_action = ' Review and continue this run to approve prepared delivery.' if status == 'awaiting_review' else ''
        if self.result:
            from .api import read_storage_maintenance
            maintenance = read_storage_maintenance(self.result.parent)
            if maintenance is not None:
                self.run_view.append_output(None, 'Storage cleanup: ' + self.redact(json.dumps(maintenance, indent=2)))
                if maintenance['status'] in {'failed', 'incomplete'}:
                    next_action += ' Storage cleanup needs attention; inspect the results for details.'
        self.status.setText(f'{status}; exit {code}. Results: {self.result}' + next_action)
