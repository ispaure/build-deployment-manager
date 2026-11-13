"""Qt-only workflow board shared by live execution and retained results."""
import json
from pathlib import Path, PurePath

from .diagnostics import MAX_LOG_BYTES, diagnose
from .run_state import RunState
from .run_test_results_ui import TimingBarDelegate  # Compatibility export.
from .workflow_presentation import display_states, format_elapsed_time, plan_overview, title

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem,
    QStackedWidget, QVBoxLayout, QWidget, QFrame, QSizePolicy, QStyle)
from .test_results import stage_label
from .ui_components import style_button, EvidenceGroup


_TERMINAL_PROBLEMS = {'failed', 'error', 'timeout', 'crashed', 'interrupted', 'cancelled', 'unknown'}


class RunView(QWidget):
    review_requested = Signal()
    attention_changed = Signal()
    diagnostics_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = RunState()
        self.rows, self.phases = {}, {}
        self.run_timing = ''
        self.selected = ''
        self.pending_refresh = self.pending_tests = False
        self.phase_log_reader = None
        self.evidence_root = None
        self.run_error = ''
        self.initial_failure_opened = False
        self.diagnosis = None
        self.review_available = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.saved_context = QLabel()
        self.saved_context.setWordWrap(True)
        self.saved_context.setTextFormat(Qt.TextFormat.PlainText)
        self.saved_context.setAccessibleName('Saved run identity')
        self.saved_context.hide()
        layout.addWidget(self.saved_context)
        from .run_summary_ui import RunOutcomeView, RunSummaryView
        self.summary_view = RunSummaryView(self)
        self.summary_view.activity_selected.connect(self.inspect_activity)
        layout.addWidget(self.summary_view)
        self.summary = self.summary_view.summary
        self.workflow_action = self.summary_view.workflow_action
        self.destinations = self.summary_view.destinations
        self.progress = self.summary_view.progress
        self.activity = self.summary_view.activity
        self.activity_buttons = self.summary_view.activity_buttons
        self.overall_tests = self.summary_view.overall_tests
        self.context = QLabel('Run source and destination will appear here.')
        self.context.setWordWrap(True)
        self.context.setAccessibleName('Source and destination of the displayed run')
        self.context.hide()  # Captured identity remains in the shared workspace.
        self.attention = QFrame()
        self.attention.setObjectName('runAttention')
        self.attention.setAccessibleName('Run needs attention')
        attention_layout = QHBoxLayout(self.attention)
        attention_layout.setContentsMargins(10, 8, 10, 8)
        self.attention_title = QLabel()
        self.attention_title.setWordWrap(True)
        self.attention_title.setTextFormat(Qt.TextFormat.PlainText)
        self.attention_title.setStyleSheet('font-weight: 600;')
        attention_layout.addWidget(self.attention_title, 1)
        attention_actions = QHBoxLayout()
        self.attention_problems = style_button(QPushButton('View problems'))
        self.attention_problems.clicked.connect(self.show_problems)
        self.attention_review = style_button(QPushButton('Review delivery…'))
        self.attention_review.clicked.connect(self.review_requested.emit)
        attention_actions.addWidget(self.attention_problems)
        attention_actions.addWidget(self.attention_review)
        attention_layout.addLayout(attention_actions)
        layout.addWidget(self.attention)
        self.attention.hide()
        self.plan = None
        from .workflow_ui import WorkflowGraphView
        self.flow = WorkflowGraphView(self, graph_only=True)
        self.flow.hide()
        self.flow.phase_selected.connect(self.select_phase)
        inspector = QWidget(self)
        inspector.hide()
        self.inspector = inspector
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(4, 0, 0, 0)
        from .run_inspector_ui import RunInspectorView
        self.step_inspector = RunInspectorView(inspector)
        self.selection_heading = self.step_inspector.selection_heading
        self.selection_info = self.step_inspector.selection_info
        inspector_layout.addWidget(self.step_inspector)
        self.substeps = QTreeWidget()
        self.substeps.setHeaderLabels(['Task / test', 'State', 'Time'])
        self.substeps.setAccessibleName('Expand the selected execution step to inspect reported tests')
        self.substeps.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.substeps.header().setStretchLastSection(False)
        self.substeps.setIndentation(14)
        self.substeps.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.substeps.setColumnWidth(1, 76)
        self.substeps.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.substeps.setColumnWidth(2, 120)
        self.substeps.setMaximumHeight(190)
        self.substeps.currentItemChanged.connect(self.inspect_subtest)
        self.substeps.itemExpanded.connect(lambda _: self.refresh_subtests(force=True))
        self.substeps.itemCollapsed.connect(lambda _: self.refresh_subtests(force=True))
        self.substeps.hide()
        inspector_layout.addWidget(self.substeps)
        self.blocking_step = style_button(QPushButton('View blocking step'))
        self.blocking_step.hide()
        self.blocking_key = ''
        self.blocking_step.clicked.connect(self.show_blocking_step)
        inspector_layout.addWidget(self.blocking_step)
        self.external_prerequisites = QComboBox()
        self.external_prerequisites.setAccessibleName('View prerequisite task')
        self.external_prerequisites.setToolTip('Show a task this step depends on. This only opens its details; it starts no work.')
        self.external_prerequisites.activated.connect(lambda index:
            self.inspect_blocking_phase(self.external_prerequisites.itemData(index)) if index else None)
        self.external_prerequisites.hide()
        inspector_layout.addWidget(self.external_prerequisites)
        from .review_ui import ReviewPlanView, text_view
        self.results_workspace = ReviewPlanView(run_mode=True)
        self.results_workspace.show_global_problems = False
        self.actions_in_footer = False
        self.tabs = EvidenceGroup(self.results_workspace.inspector_tabs)
        self.tabs.pages.append(self.results_workspace.details_scroll)
        self.tabs.labels.append('Summary')
        self.results_workspace.phase_selected.connect(self.select_phase)
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.pages.setAccessibleName('Workflow cards and step inspection')
        self.pages.addWidget(self.results_workspace)
        self.summary_page = self.results_workspace.details_scroll
        self.outcome_view = RunOutcomeView()
        self.results_workspace.run_summary_layout.insertWidget(0, self.outcome_view)
        self.outcome_view.failed_case_requested.connect(self.show_diagnosed_test)
        self.outcome_view.logs_requested.connect(self.show_diagnosed_logs)
        self.outcome_view.blocker_requested.connect(self.show_blocking_step)
        self.outcome_view.files_requested.connect(lambda: self.tabs.setCurrentWidget(self.delivery_page))
        self.outcome_view.diagnostics_requested.connect(lambda: self.diagnostics_requested.emit(self.selected))
        self.delivered = QTreeWidget()
        self.delivered.setHeaderLabels(['Destination / prepared file', 'Outcome', 'Identity / location'])
        self.delivered.setAccessibleName('Delivery outcomes and retained files')
        self.delivered.setColumnWidth(0, 240)
        self.delivered.setColumnWidth(1, 150)
        self.delivered.setAlternatingRowColors(True)
        self.delivered.itemActivated.connect(self.inspect_delivered)
        self.delivery_page = QWidget()
        delivery_layout = QVBoxLayout(self.delivery_page)
        delivery_layout.addWidget(self.delivered, 1)
        self.inspect_delivery = style_button(QPushButton('Inspect selected result'))
        self.inspect_delivery.setEnabled(False)
        self.inspect_delivery.clicked.connect(lambda: self.inspect_delivered(self.delivered.currentItem()))
        self.delivered.currentItemChanged.connect(lambda item: self.inspect_delivery.setEnabled(item is not None))
        delivery_layout.addWidget(self.inspect_delivery)
        layout.addWidget(self.pages, 1)
        summary_layout = self.results_workspace.run_summary_layout
        summary_layout.insertWidget(1, self.activity)
        for control in (self.workflow_action, self.progress, self.overall_tests):
            control.setParent(self.summary_view)
            control.hide()
        from .run_test_results_ui import TestResultsView
        self.test_results = TestResultsView(self)
        self.test_results.problems_requested.connect(self.show_problem_tests)
        self.test_results.diagnostics_requested.connect(self.request_test_diagnostics)
        self.result_counts = self.test_results.result_counts
        self.count_cards = self.test_results.count_cards
        self.problems_button = self.test_results.problems_button
        self.search = self.test_results.search
        self.find_tests = self.test_results.find_tests
        self.filter = self.test_results.filter
        self.stage_filter = self.test_results.stage_filter
        self.test_matches = self.test_results.test_matches
        self.test_summary = self.test_results.test_summary
        self.tests = self.test_results.tests
        self.test_detail = self.test_results.test_detail
        self.timing_summary = self.test_results.timing_summary
        self.timings = self.test_results.timings
        self.next_action = self.step_inspector.next_action
        self.steps = QTreeWidget(self.summary_page)
        self.steps.setHeaderLabels(['Step', 'State / waiting reason', 'Duration', 'Kind', 'Depends on'])
        self.steps.setAccessibleName('Workflow steps and timings')
        self.steps.setColumnWidth(0, 220)
        self.steps.setColumnWidth(1, 250)
        self.steps.setAlternatingRowColors(True)
        self.steps.currentItemChanged.connect(self.select_step_item)
        # The graph is the step browser; this hidden model tracks evidence selection.
        self.steps.hide()
        self.detail = self.step_inspector.detail
        self.technical = self.results_workspace.plan_tabs
        self.technical.addTab(self.detail, 'Step record')
        self.report_view = text_view('Complete redacted run report', deferred=True)
        self.technical.addTab(self.report_view, 'Run report')
        self.storage_view = text_view('Recorded storage maintenance', deferred=True)
        self.technical.addTab(self.storage_view, 'Storage maintenance')
        self.technical.navigator.currentChanged.connect(self.materialize_report)
        self.results_workspace.technical_section.toggle.toggled.connect(self.materialize_report)
        self.tabs.addTab(self.test_results, 'Tests')
        from .run_output_ui import RunOutputView
        self.output = RunOutputView(self)
        self.log, self.log_notice = self.output.log, self.output.notice
        self.tabs.addTab(self.output, 'Logs')
        self.tabs.addTab(self.delivery_page, 'Artifacts')
        self.tabs.navigator.currentChanged.connect(self.open_evidence)
        self.set_report(None)
        self.set_storage_maintenance(None)
        # The same persistent overview/task/detail workspace owns review and run.
        # Run-only evidence supplements its inspector instead of replacing it.

    def show_results_tab(self):
        self.tabs.activate()

    def show_summary(self):
        self.tabs.setCurrentWidget(self.summary_page)

    def materialize_report(self, _):
        if self.results_workspace.technical_section.toggle.isChecked():
            page = self.technical.navigator.currentWidget()
            if page in (self.report_view, self.storage_view):
                page.materialize()

    def set_report(self, report):
        self.report_view.defer(lambda: json.dumps(report, indent=2) if report is not None
                               else 'No verified run report is available.')
        self.materialize_report(None)

    def set_storage_maintenance(self, data):
        self.storage_view.defer(lambda: json.dumps(data, indent=2) if data is not None else '')
        index = self.technical.indexOf(self.storage_view)
        self.technical.setTabVisible(index, data is not None)
        self.materialize_report(None)

    def select_group(self, key):
        self.flow.selected = ''
        self.select_phase('')
        self.tabs.setCurrentIndex(0)
        if key:
            keys = self.results_workspace.flow.group_keys(key)
            priority = ('unknown', 'failed', 'error', 'timeout', 'running', 'awaiting_review', 'blocked')
            chosen = next((name for state in priority for name in keys
                if self.flow.canvas.states[name][0] == state), next(iter(keys), ''))
            if chosen:
                self.flow.select(chosen)
                self.show_summary()
            self.flow.setVisible(bool(keys))

    def open_step_group(self, key):
        if key and self.results_workspace.selected != key:
            # Selection is mirrored without sending it back through select_phase.
            self.results_workspace.blockSignals(True)
            try:
                self.results_workspace.inspect_phase(key)
            finally:
                self.results_workspace.blockSignals(False)

    @property
    def facts(self):
        return self.state.facts

    @property
    def started(self):
        return self.state.started_at_by_phase

    @property
    def outcome(self):
        return self.state.outcome

    @property
    def cancelling(self):
        return self.state.cancelling

    def live_facts(self):
        return self.state.snapshot()

    def filter_delivered(self):
        keys = self.scoped_facts() if self.plan else {}
        # Prepared inputs belong with the action consuming them, even when the
        # preparation step lives in a different overview card.
        artifact_keys = set(keys)
        pending = list(keys)
        while pending:
            phase = self.phases.get(pending.pop())
            for key in phase.dependencies if phase else ():
                if key not in artifact_keys:
                    artifact_keys.add(key)
                    pending.append(key)
        visible, deliveries = False, False
        for index in range(self.delivered.topLevelItemCount()):
            row = self.delivered.topLevelItem(index)
            children = [row.child(i) for i in range(row.childCount())]
            for child in children:
                child.setHidden(child.data(0, Qt.ItemDataRole.UserRole) not in keys)
            identity = row.data(0, Qt.ItemDataRole.UserRole + 1)
            relevant = artifact_keys if identity and identity[0] == 'artifact' else keys
            row.setHidden(not any(not child.isHidden() for child in children) if children
                else row.data(0, Qt.ItemDataRole.UserRole) not in relevant)
            if not row.isHidden():
                visible = True
                deliveries |= identity[0] == 'destination'
        selected = self.delivered.currentItem()
        if selected and (selected.isHidden() or selected.parent() and selected.parent().isHidden()):
            self.delivered.setCurrentItem(None)
        label = 'Deliveries' if deliveries else 'Artifacts'
        index = self.tabs.indexOf(self.delivery_page)
        self.tabs.labels[index] = label
        navigator = self.tabs.navigator
        entry = navigator.entries[navigator.indexOf(self.delivery_page)]
        if entry['label'] != label or entry['visible'] != visible:
            entry['label'] = label
            self.tabs.setTabVisible(index, visible)
        self.outcome_view.files.setText('View ' + label.lower())

    def set_detail_text(self, text, key):
        self.step_inspector.set_detail_text(text, key)

    def inspect_summary_phase(self, key):
        tab = self.results_workspace.inspector_tabs.currentWidget()
        self.open_step_group(key)
        self.flow.select(key)
        self.restore_inspector_tab(tab)
        self.results_workspace.tasks.setFocus()

    def restore_inspector_tab(self, tab):
        navigator = self.results_workspace.inspector_tabs
        if navigator.isTabVisible(navigator.indexOf(tab)):
            navigator.setCurrentWidget(tab)
        else:
            navigator.setCurrentWidget(self.results_workspace.details_scroll)

    def inspect_blocking_phase(self, key):
        self.inspect_summary_phase(key)
        self.show_summary()
        self.results_workspace.tasks.setFocus()

    def scoped_facts(self):
        if self.plan is None:
            return {}
        grouped = self.results_workspace.flow
        keys = (self.selected,) if self.selected else grouped.group_keys(grouped.selected) if grouped.has_group_scope() else self.facts
        return {key: fact for key, fact in self.facts.items() if key in keys}

    def inspect_phase_problems(self, key, test_id=''):
        self.inspect_summary_phase(key)
        self.show_problem_tests(test_id)
        self.tests.setFocus()

    def select_first_problem_test(self, test_id=''):
        first = None
        for index in range(self.tests.topLevelItemCount()):
            item = self.tests.topLevelItem(index)
            if not item.isHidden():
                first = first or item
                case = item.data(0, Qt.ItemDataRole.UserRole)
                if test_id and self.case_identity(case) == test_id:
                    first = item
                    break
        if first is not None:
            self.tests.setCurrentItem(first)
            self.tests.scrollToItem(first)

    @staticmethod
    def case_identity(case):
        return '.'.join(filter(None, (case.get('classname'), case.get('name'))))

    def selected_test_identity(self):
        item = self.tests.currentItem()
        if self.tabs.navigator.currentWidget() is self.test_results and item is not None:
            return item.text(4), self.case_identity(item.data(0, Qt.ItemDataRole.UserRole))
        return '', ''

    def request_test_diagnostics(self):
        key, _ = self.selected_test_identity()
        if key:
            self.diagnostics_requested.emit(key)

    def select_step_item(self, item, previous=None):
        if item is not None and item.text(0) != self.selected:
            self.flow.select(item.text(0))
        self.show_detail(item)

    def select_phase(self, key):
        if key:
            tab = self.results_workspace.inspector_tabs.currentWidget()
            self.open_step_group(key)
            self.restore_inspector_tab(tab)
            self.flow.selected = key
            self.flow.set_facts(self.live_facts())
        self.selected = key
        if key:
            self.steps.setCurrentItem(self.rows.get(key))
        else:
            self.steps.setCurrentItem(None)
            self.detail.clear()
            self.flow.selected = ''
            self.flow.set_facts(self.live_facts())
        scope = self.scoped_facts()
        for name, row in self.rows.items():
            row.setHidden(name not in scope)
        self.refresh_inspector()
        self.refresh_tests()
        self.refresh_output()
        self.filter_delivered()
        self.refresh_outcome()

    def inspect_subtest(self, item, previous=None):
        if item is None or item.parent() is None:
            return
        case = item.data(0, Qt.ItemDataRole.UserRole + 1)
        self.test_detail.setPlainText('\n'.join(filter(None, (
            case.get('classname'), case['name'], 'Stage: ' + stage_label(case), item.text(1), item.text(2), case.get('message')))))
        self.test_detail.show()
        self.tabs.setCurrentWidget(self.test_results)

    def refresh_subtests(self, *, force=False):
        from .workflow_presentation import title
        from .test_tree_ui import update_test_children, time_share, visible_tree_rows
        key = self.selected
        live = self.live_facts()
        keys = tuple(name for name in (self.scoped_facts() if not key else (key,)) if name in self.phases)
        fact = live.get(key, {})
        show = bool(keys) and (not key or bool(fact.get('tests') or fact.get('live_tests') or
            fact.get('current_test') or getattr(self.phases.get(key), 'test_files', ()) or
            'junit' in getattr(self.phases.get(key), 'artifact_types', {}).values()))
        self.substeps.blockSignals(True)
        if getattr(self, 'subtest_phase', None) != keys:
            self.substeps.clear()
            self.subtest_phase = keys
        self.substeps.setVisible(show)
        count = 0
        if show:
            for index, key in enumerate(keys):
                fact = live.get(key, {})
                cases = fact.get('tests') or fact.get('live_tests', ())
                row = self.substeps.topLevelItem(index)
                if row is None:
                    row = QTreeWidgetItem()
                    self.substeps.addTopLevelItem(row)
                phase = self.phases[key]
                row.setText(0, getattr(phase, 'label', '') or key.rsplit('.', 1)[-1].replace('_', ' ').replace('-', ' ').capitalize())
                row.setToolTip(0, title(phase))
                row.setText(1, 'Reused' if fact.get('reused') else fact.get('status', 'planned').capitalize())
                if fact.get('recovery', {}).get('status') == 'recovered':
                    row.setText(1, 'Passed after recovery')
                row.setToolTip(1, f'{len(cases)} reported tests')
                row.setText(2, format_elapsed_time(fact.get('seconds')))
                update_test_children(row, key, fact, self.phases[key], force=force)
                time_share(self.substeps, row, fact.get('reuse', {}).get('original_seconds') if fact.get('reused') else fact.get('seconds'),
                           sum(live.get(name, {}).get('seconds') or 0 for name in keys if not live.get(name, {}).get('reused')),
                           reused=fact.get('reused', False))
                count += visible_tree_rows(row)
            self.substeps.setFixedHeight(min(240, max(150,
                self.substeps.header().height() + (self.substeps.fontMetrics().height() + 12) * count + 4)))
        self.substeps.blockSignals(False)

    def refresh_inspector(self):
        if self.plan is None:
            return
        self.refresh_subtests()
        from .workflow_presentation import blocking_prerequisite
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, self.selected) if self.plan else ''
        self.blocking_step.setVisible(bool(self.blocking_key))
        external = ()
        if self.selected:
            phase = self.phases[self.selected]
            external = tuple(key for key in (*phase.dependencies, *getattr(phase, 'waits_for', ()))
                if key not in self.flow.canvas.cards)
        if external != getattr(self, 'external_dependency_keys', None):
            self.external_dependency_keys = external
            self.external_prerequisites.clear()
            self.external_prerequisites.addItem('View prerequisite task…', '')
            from .workflow_presentation import title
            for key in external:
                self.external_prerequisites.addItem(title(self.phases[key]), key)
        self.external_prerequisites.setVisible(self.external_prerequisites.count() > 1)
        if not self.selected:
            grouped = self.results_workspace.flow
            in_group = grouped.has_group_scope()
            information = ('Select a step to inspect its status, tests, timing and output.' if in_group else
                'Open a workflow card to inspect its steps, tests, timing and output.')
            self.step_inspector.show_group(grouped.heading.text() if in_group else 'Whole workflow',
                information, grouped.group_context() if in_group else information)
            return
        phase = self.phases[self.selected]
        state, reason = self.flow.canvas.states.get(self.selected, ('queued', ''))
        self.step_inspector.show_phase(self.plan, phase,
            self.live_facts().get(self.selected, {}), state, reason, self.phases)
        self.show_detail(self.rows.get(self.selected))

    def refresh_outcome(self):
        if not self.plan:
            if self.run_error:
                self.diagnosis = diagnose(None, {}, outcome=self.outcome, run_error=self.run_error)
                self.outcome_view.present(heading=self.diagnosis.title, message=self.diagnosis.message,
                    guidance='', problems='', deliveries='', logs=True, diagnostics=True)
            return
        scoped = self.scoped_facts()
        states = display_states(self.plan, self.facts)
        state = states.get(self.selected, ('', ''))[0]
        active_failure = state in _TERMINAL_PROBLEMS | {'blocked', 'skipped'} or self.selected and any(
            case.get('status') in {'failed', 'error'} for case in scoped.get(self.selected, {}).get('tests', ()))
        if self.selected and not active_failure:
            diagnosis = None
        else:
            diagnosis = diagnose(self.plan, self.facts if self.selected else scoped, outcome=self.outcome,
                selected=self.selected, run_error=self.run_error)
            if diagnosis.category == 'error' and diagnosis.step_id and not self.facts[diagnosis.step_id].get('error'):
                diagnosis = diagnose(self.plan, self.facts, outcome=self.outcome,
                    selected=diagnosis.step_id, run_error=self.run_error, log_text=self.diagnostic_log(diagnosis.step_id))
        self.diagnosis = diagnosis
        label = self.results_workspace.task_names.get(self.selected, self.selected)
        heading = diagnosis.title if diagnosis and diagnosis.category != 'none' else ''
        message = diagnosis.message if heading else ''
        if diagnosis and diagnosis.hint:
            message = 'From captured logs\n' + message
        if self.selected and state in {'blocked', 'skipped'} and self.blocking_key:
            blocker = self.results_workspace.task_names.get(self.blocking_key, self.blocking_key)
            heading = 'Blocked · ' + label
            message = 'This step did not run because ' + blocker + ' did not pass.'
        unknown = self.outcome == 'unknown' or any(fact['status'] == 'unknown' for fact in self.facts.values())
        guidance = ('An action may already have taken effect. Check its outcome with the provider before retrying.'
                    if unknown and not self.run_error else '')
        if self.run_error and (not diagnosis or diagnosis.category != 'run'):
            guidance = self.run_error
        if not guidance and self.outcome == 'awaiting_review':
            guidance = self.workflow_action.text()
        elif not guidance and self.selected and not heading and state in {'running', 'retrying', 'waiting_resource'}:
            guidance = self.next_action.text()
        other = [title(phase) for phase in self.plan.phases
                 if self.facts[phase.id]['status'] in _TERMINAL_PROBLEMS - {'unknown', 'cancelled'}
                 and phase.id != self.blocking_key
                 and (not diagnosis or phase.id != diagnosis.step_id)]
        problems = ('Other failed steps · ' + ', '.join(other[:5]) +
                    (f' · {len(other) - 5} more' if len(other) > 5 else '')) if other else ''
        delivery_counts = self.delivery_counts()
        deliveries = ('Workflow deliveries · ' + ' · '.join(f'{count} {status}' for status, count in delivery_counts.items())
                      if delivery_counts and (self.outcome or unknown) else '')
        key = diagnosis.step_id if diagnosis and diagnosis.step_id else self.selected
        logs = bool(key and (self.facts.get(key, {}).get('log') or active_failure or
            any(phase == key for phase, _ in self.output.lines))) or bool(self.run_error)
        self.outcome_view.present(heading=heading, message=message, guidance=guidance, problems=problems,
            deliveries=deliveries, case=bool(diagnosis and diagnosis.test_id), logs=logs,
            blocker=bool(self.blocking_key), files=self.tabs.isTabVisible(self.tabs.indexOf(self.delivery_page)),
            diagnostics=bool(self.outcome or heading))

    def delivery_counts(self):
        counts = {}
        for index in range(self.delivered.topLevelItemCount()):
            item = self.delivered.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole + 1)[0] == 'destination':
                state = item.text(1).lower()
                counts[state] = counts.get(state, 0) + 1
        return counts

    def append_output(self, phase, text):
        self.output.append(phase, text, selected=self.selected, keys=self.scoped_facts())

    def refresh_output(self):
        scope = self.scoped_facts()
        reference = scope.get(self.selected, {}).get('log')
        terminal = bool(self.outcome) or scope.get(self.selected, {}).get('status') in _TERMINAL_PROBLEMS | {'passed', 'skipped'}
        self.output.show_scope(selected=self.selected, keys=scope, reader=self.phase_log_reader,
            reference=reference, terminal=terminal, card=self.results_workspace.flow.has_group_scope(),
            retained_steps=any(fact.get('log') for fact in scope.values()))

    def show_problem_tests(self, test_id=''):
        self.search.clear()
        self.stage_filter.setCurrentIndex(0)
        self.filter.setCurrentText('Problems')
        self.test_results.timing_button.setChecked(False)
        self.tabs.setCurrentWidget(self.test_results)
        self.select_first_problem_test(test_id)

    def show_blocking_step(self):
        if self.blocking_key:
            self.inspect_blocking_phase(self.blocking_key)

    def has_problems(self):
        return self.outcome in _TERMINAL_PROBLEMS or any(
            row.get('status') in _TERMINAL_PROBLEMS or any(
                case['status'] in {'failed', 'error'} for case in row.get('tests', ()))
            for row in self.facts.values())

    def diagnostic_log(self, key):
        fact = self.facts.get(key, {})
        evidence = self.output.read_step(key, fact.get('log'), self.phase_log_reader)
        if evidence.text:
            return evidence.text
        if key in self.output.dropped or not key and None in self.output.dropped:
            return ''  # The live prefix is no longer available.
        text = '\n'.join(line for phase, line in self.output.lines if phase == (key or None))
        raw = text.encode('utf-8', errors='replace')
        if len(raw) > MAX_LOG_BYTES:
            return raw[:MAX_LOG_BYTES].rpartition(b'\n')[0].decode('utf-8', errors='ignore')
        return text

    def show_logs(self, key=''):
        if key:
            self.inspect_summary_phase(key)
        if self.tabs.navigator.currentWidget() is self.output:
            self.open_evidence(None)
        else:
            self.tabs.setCurrentWidget(self.output)
        self.log.setFocus()

    def open_evidence(self, _):
        if self.tabs.navigator.currentWidget() is self.output:
            self.output.cached_log = None
            self.refresh_output()
        elif self.tabs.navigator.currentWidget() is self.delivery_page:
            self.refresh_artifact_availability()

    def show_diagnosed_test(self):
        if self.diagnosis and self.diagnosis.test_id:
            self.inspect_phase_problems(self.diagnosis.step_id, self.diagnosis.test_id)

    def show_diagnosed_logs(self):
        if self.diagnosis and self.diagnosis.category == 'run' and self.run_error:
            if self.plan:
                self.results_workspace.flow.close_group()
                self.flow.select('')
            self.show_logs()
        else:
            self.show_logs(self.diagnosis.step_id if self.diagnosis and self.diagnosis.step_id else self.selected)

    def show_problems(self):
        """Leave any selected successful card and reveal the actual problem."""
        self.open_failure(show_test=True)

    def open_failure(self, *, show_test=False):
        diagnosis = diagnose(self.plan, self.facts, outcome=self.outcome, run_error=self.run_error)
        if diagnosis.test_id and show_test:
            self.inspect_phase_problems(diagnosis.step_id, diagnosis.test_id)
        elif diagnosis.step_id:
            self.inspect_blocking_phase(diagnosis.step_id)
        else:
            if self.plan:
                self.results_workspace.flow.close_group()
                self.flow.select('')
            self.show_summary()
            if self.run_error:
                self.set_detail_text(self.run_error, None)

    def set_review_available(self, available):
        self.review_available = available
        self.attention_review.setEnabled(available)
        self.attention_review.setToolTip('Inspect retained evidence before approving any action.' if available
            else 'Review becomes available when the active operation has stopped and retained evidence can be verified.')

    def refresh_attention(self):
        failed_keys = [key for key, row in self.facts.items() if row['status'] in {'failed', 'error', 'timeout'}]
        failures = len(failed_keys)
        unknown = self.outcome == 'unknown' or any(row['status'] == 'unknown' for row in self.facts.values())
        approvals = sum(row['status'] == 'awaiting_review' for row in self.facts.values())
        problems = self.has_problems()
        needs_review = bool(approvals or self.outcome == 'awaiting_review')
        labels = []
        if unknown:
            labels.append('Unknown outcome · check provider status before retrying')
        elif failures:
            from .workflow_presentation import title
            names = ', '.join(title(self.phases[key]) if key in self.phases else key for key in failed_keys[:2])
            labels.append(f'{failures} failed step' + ('s' if failures != 1 else '') + ' · ' + names)
        elif problems:
            labels.append('Run interrupted or unsuccessful · inspect the retained result')
        if needs_review:
            labels.append(f'{approvals} action' + ('s' if approvals != 1 else '') + ' waiting for approval'
                          if approvals else 'Actions waiting for approval')
        self.attention_title.setText('Attention: ' + ' · '.join(labels))
        self.attention_problems.setVisible(problems and not self.actions_in_footer)
        self.attention_problems.setText('Inspect unknown outcome' if unknown else 'View problems')
        self.attention_review.setVisible(needs_review and not self.actions_in_footer)
        dispatch = any(row['status'] == 'awaiting_review' and key in self.phases and
            (row.get('effect') or (self.phases[key].effect if self.phases[key].effect != 'inherit' else self.plan.effect)) == 'dispatch'
            for key, row in self.facts.items())
        self.attention_review.setText('Review GitHub checks…' if dispatch else 'Review delivery…')
        color = '#c54040' if problems else '#b37c12'
        self.attention.setStyleSheet('QFrame#runAttention { border: 1px solid palette(mid); '
            'border-left: 4px solid ' + color + '; border-radius: 6px; background: palette(alternate-base); }')
        self.attention.setVisible(problems or needs_review)
        self.attention_changed.emit()

    def show_timings(self):
        if not self.test_results.timing_button.isHidden():
            self.tabs.setCurrentWidget(self.test_results)
            self.test_results.timing_button.setChecked(True)

    def reset(self, plan, previous=(), *, fields=(), capability=None, proposal=None):
        self.saved_context.hide()
        self.pending_refresh = self.pending_tests = False
        self.phase_log_reader = None
        self.evidence_root = None
        self.run_error = ''
        self.initial_failure_opened = False
        self.plan = plan
        self.selected = ''
        self.results_workspace.blockSignals(True)
        try:
            self.results_workspace.reset(plan, fields, preview=False, capability=capability, proposal=proposal,
                                   summary=plan_overview(plan))
        finally:
            self.results_workspace.blockSignals(False)
        self.pages.setCurrentIndex(0)
        self.delivered.clear()
        self.delivery_signature = None
        self.output.reset()
        self.set_report(None)
        self.set_storage_maintenance(None)
        self.flow.reset(plan)
        self.flow.hide()
        self.inspector.hide()
        self.rows = {}
        self.state.reset(plan.phases)
        self.step_inspector.detail_key = None
        self.external_dependency_keys = None
        self.phases = {phase.id: phase for phase in plan.phases}
        from .plan_summary import captured_choices
        source = captured_choices(plan)[0][1]
        self.context.setText(f'{plan.project} · {plan.operation} · ' + source.replace('\n', ' · '))
        self.context.setToolTip(source)
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.run_timing = ''
        self.set_review_available(False)
        self.steps.clear()
        self.test_results.reset()
        self.detail.clear()
        self.log.clear()
        for phase in plan.phases:
            row = QTreeWidgetItem([phase.id, 'queued', '—', phase.kind, ', '.join(phase.dependencies) or '—'])
            self.steps.addTopLevelItem(row)
            self.rows[phase.id] = row
        for event in previous:
            self.update_phase(event)
        self.refresh_summary()
        self.refresh_tests()
        self.show_summary()
        self.refresh_inspector()
        self.refresh_output()
        self.results_workspace.inspector_tabs.setCurrentWidget(self.results_workspace.details_scroll)

    def update_phase(self, event, *, refresh=True):
        key = event['id']
        if key not in self.rows:
            self.rows[key] = QTreeWidgetItem([key, '', '', '', ''])
            self.steps.addTopLevelItem(self.rows[key])
        previous = self.facts.get(key, {}).get('status')
        fact = self.state.update(event)
        self.rows[key].setText(1, 'reused' if fact.get('reused') else fact['status'].replace('_', ' '))
        if fact.get('recovery', {}).get('status') == 'recovered':
            self.rows[key].setText(1, 'passed after recovery')
        self.rows[key].setToolTip(1, fact.get('reason') or fact.get('error', ''))
        if event['status'] != 'running' and 'seconds' in event:
            self.rows[key].setText(2, format_elapsed_time(event['seconds']))
        self.pending_refresh = True
        self.pending_tests |= previous != fact['status'] or 'tests' in event or 'live_tests' in event
        if refresh:
            self.flush_updates()

    def flush_updates(self):
        if not self.pending_refresh:
            return
        self.pending_refresh = False
        self.flow.set_facts(self.live_facts())
        self.refresh_summary()
        if self.pending_tests:
            self.pending_tests = False
            self.refresh_tests()
        if self.selected and self.selected in self.facts:
            self.refresh_output()

    def tick(self):
        if self.pending_refresh:
            self.flush_updates()
            return
        for key, started in self.started.items():
            elapsed = format_elapsed_time(self.state.clock() - started)
            self.rows[key].setText(2, elapsed)
            if key in self.flow.canvas.cards:
                self.flow.canvas.cards[key][1].setText('Running · ' + elapsed)
        facts = self.live_facts()
        self.flow.set_facts(facts)
        self.results_workspace.set_facts(facts)
        self.refresh_inspector()

    def refresh_summary(self):
        self.summary_view.present(self.plan, self.facts, outcome=self.outcome,
            cancelling=self.cancelling, run_timing=self.run_timing, total_steps=len(self.rows))
        self.results_workspace.set_facts(self.live_facts())
        self.next_action.setText(self.workflow_action.text())
        self.refresh_inspector()
        self.refresh_attention()
        self.refresh_delivered()
        self.refresh_outcome()

    def inspect_activity(self, state):
        key = next((key for key, (value, _) in display_states(self.plan, self.facts).items()
                    if value == state), None)
        if key:
            self.inspect_blocking_phase(key)

    def cancellation_requested(self):
        self.state.cancelling = True
        self.refresh_summary()

    def refresh_delivered(self):
        from .journeys import outcomes
        if not self.plan:
            return
        displayed = display_states(self.plan, self.facts)
        signature = (self.evidence_root, bool(self.outcome), tuple(
            (key, displayed.get(key, (fact['status'], ''))[0], tuple((a['path'], a.get('sha256', ''))
            for a in fact.get('artifacts', ()))) for key, fact in self.facts.items()))
        if getattr(self, 'delivery_signature', None) == signature:
            return
        self.delivery_signature = signature
        selected = self.delivered.currentItem()
        identity = selected.data(0, Qt.ItemDataRole.UserRole + 1) if selected else None
        expanded = {self.delivered.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1)
            for i in range(self.delivered.topLevelItemCount()) if self.delivered.topLevelItem(i).isExpanded()}
        scroll = self.delivered.verticalScrollBar().value()
        self.delivered.clear()
        journey = getattr(self.plan, 'journey', {})
        states = dict(outcomes(self.plan, (dict(id=key, status=state)
            for key, (state, _) in displayed.items()))) if journey else {}
        labels = {'passed': 'Delivered', 'awaiting_review': 'Needs approval', 'unknown': 'Unknown outcome',
                  'skipped': 'Not delivered', 'queued': 'Not started', 'blocked': 'Blocked'}
        for destination in journey.get('destinations', {}).values():
            state = states[destination['identity']]
            row = QTreeWidgetItem([destination['identity'], labels.get(state, state.replace('_', ' ').capitalize()), ''])
            row.setToolTip(0, destination['identity'])
            icon = (QStyle.StandardPixmap.SP_DialogApplyButton if state == 'passed' else
                QStyle.StandardPixmap.SP_MessageBoxCritical if state in {'unknown', 'failed', 'error', 'timeout'}
                else QStyle.StandardPixmap.SP_MessageBoxWarning)
            row.setIcon(1, self.style().standardIcon(icon))
            priority = ('unknown', 'failed', 'error', 'timeout', 'interrupted', 'cancelled',
                        'blocked', 'skipped', 'awaiting_review', 'running')
            key = next((key for state in priority for key in destination['steps']
                if displayed[key][0] == state), destination['steps'][0])
            row.setData(0, Qt.ItemDataRole.UserRole, key)
            row.setData(0, Qt.ItemDataRole.UserRole + 1, ('destination', destination['identity']))
            for key in destination['steps']:
                child = QTreeWidgetItem([getattr(self.phases[key], 'label', '') or key,
                    labels.get(displayed[key][0], displayed[key][0].replace('_', ' ').capitalize()), ''])
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, ('step', key))
                row.addChild(child)
            self.delivered.addTopLevelItem(row)
        for key, fact in self.facts.items():
            for artifact in fact.get('artifacts', ()):
                path = artifact['path']
                name = PurePath(artifact.get('original_path') or path).name
                row = QTreeWidgetItem([name, self.artifact_status(path), path])
                row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                row.setToolTip(0, 'SHA-256: ' + artifact.get('sha256', 'Not recorded'))
                row.setToolTip(2, path)
                row.setData(0, Qt.ItemDataRole.UserRole, key)
                row.setData(0, Qt.ItemDataRole.UserRole + 1, ('artifact', key, path))
                self.delivered.addTopLevelItem(row)
        for index in range(self.delivered.topLevelItemCount()):
            row = self.delivered.topLevelItem(index)
            row.setExpanded(row.data(0, Qt.ItemDataRole.UserRole + 1) in expanded)
            for item in (row, *(row.child(i) for i in range(row.childCount()))):
                if identity and item.data(0, Qt.ItemDataRole.UserRole + 1) == identity:
                    self.delivered.setCurrentItem(item)
        self.delivered.verticalScrollBar().setValue(scroll)
        self.filter_delivered()

    def refresh_artifact_availability(self):
        for index in range(self.delivered.topLevelItemCount()):
            item = self.delivered.topLevelItem(index)
            identity = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if identity[0] == 'artifact' and not item.isHidden():
                item.setText(1, self.artifact_status(identity[2]))

    def artifact_status(self, path):
        available = self.artifact_available(path)
        if available is False:
            return 'File missing · record retained'
        if available is None and self.evidence_root:
            return 'Availability unverified'
        return 'Retained file'

    def artifact_available(self, value):
        if self.evidence_root is None:
            return None
        try:
            root = Path(self.evidence_root).resolve()
            path = (root / value).resolve()
            return path.is_file() if path.is_relative_to(root) else None
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

    def inspect_delivered(self, item, column=0):
        if item:
            self.inspect_blocking_phase(item.data(0, Qt.ItemDataRole.UserRole))
            if item.data(0, Qt.ItemDataRole.UserRole + 1)[0] == 'artifact':
                self.results_workspace.technical_section.toggle.setChecked(True)
                self.technical.setCurrentWidget(self.detail)
                self.summary_page.ensureWidgetVisible(self.detail)

    def complete(self, report):
        self.state.complete(report['status'])
        self.run_timing = ' · Active time: ' + format_elapsed_time(report.get('seconds'))
        if report.get('attempts'):
            self.run_timing += f' across {len(report["attempts"])} attempt(s)'
        self.flow.set_facts(self.facts)
        self.refresh_summary()
        self.refresh_tests()
        self.refresh_output()
        self.open_initial_failure()

    def open_initial_failure(self):
        if not self.initial_failure_opened and self.has_problems():
            self.initial_failure_opened = True
            self.open_failure()
            self.summary_page.verticalScrollBar().setValue(0)

    def set_run_error(self, reason):
        self.run_error = reason

    def unverified(self, reason):
        self.set_run_error(reason)
        self.state.complete('failed')
        self.run_timing = ' · Result could not be verified'
        for key, fact in list(self.facts.items()):
            if fact['status'] == 'running':
                self.update_phase(dict(id=key, status='unknown', reason='Process ended without a verified result.'))
        self.refresh_summary()
        self.refresh_output()
        self.open_initial_failure()

    def show_detail(self, item, previous=None):
        if item is None:
            return
        key = item.text(0)
        fact, phase = self.facts.get(key, {}), self.phases.get(key)
        from .workflow_presentation import display_states, state_label, format_step_time
        state, reason = display_states(self.plan, self.facts)[key]
        lines = [key, 'State: ' + state_label(state)]
        if reason:
            lines.append(reason)
        elapsed = format_step_time(self.live_facts().get(key, fact), state)
        if elapsed:
            lines.append('Step duration: ' + elapsed)
        for field in ('reason', 'error', 'summary', 'cleanup_error'):
            if fact.get(field) and fact[field] != reason:
                lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
        if fact.get('exit_code') is not None:
            lines.append('Exit code: ' + str(fact['exit_code']))
        problems = [case for case in fact.get('tests', []) if case['status'] in {'failed', 'error'}]
        for case in problems[:3]:
            lines += ['', case['name'] + ': ' + case['status'], case['message']]
        for observation in fact.get('observed_test_failures', ()):
            lines += ['', observation.get('name', 'Test') + ' · ' + observation['status'], observation.get('message', '')]
        if phase:
            from .workflow_presentation import title
            lines += ['', f'Gate: {"required" if phase.required else "optional"}',
                      'Dependencies: ' + (', '.join(title(self.phases[name]) for name in phase.dependencies) or 'none'),
                      'Timeout: ' + format_elapsed_time(phase.timeout)]
            if getattr(phase, 'waits_for', ()):
                lines.append('Scheduling only: wait for completion of ' + ', '.join(phase.waits_for))
        if fact.get('log'):
            lines.append('Log in results folder: ' + str(fact['log']))
        for artifact in fact.get('artifacts', []):
            lines += ['Artifact: ' + artifact['path'], 'SHA-256: ' + artifact['sha256']]
        grouped = self.results_workspace.flow
        if grouped.has_group_scope():
            lines += ['', grouped.group_context()]
        # Caller supplies redacted plan data; report facts are redacted by executor.
        self.set_detail_text('\n'.join(lines), key)

    def refresh_tests(self):
        scope = self.scoped_facts()
        declared = [fact for key, fact in scope.items() if key in self.phases and
            'junit' in self.phases[key].artifact_types.values()]
        absent = [fact for fact in declared if not fact.get('tests')]
        report_status = ''
        if absent:
            terminal = any(fact.get('status') in _TERMINAL_PROBLEMS | {'passed', 'skipped'} for fact in absent)
            if self.outcome or terminal:
                report_status = ('Some declared test reports are unavailable.' if any(fact.get('tests') for fact in scope.values())
                                 else 'No cases are available from the declared test report.')
            else:
                report_status = 'Cases will appear when the declared test report is captured.'
        relevant = bool(declared or any(fact.get('tests') or fact.get('live_tests') for fact in scope.values()))
        index = self.tabs.indexOf(self.test_results)
        if self.tabs.isTabVisible(index) != relevant:
            self.tabs.setTabVisible(index, relevant)
        if not self.test_results.present(scope, selected=bool(self.selected), report_status=report_status):
            return
        current = self.substeps.currentItem()
        if current is not None and current.parent() is not None and self.tabs.currentWidget() == self.test_results:
            self.inspect_subtest(current)

    def filter_tests(self, *_):
        self.test_results.filter_tests()

    def show_test(self, item, previous=None):
        self.test_results.show_test(item, previous)
