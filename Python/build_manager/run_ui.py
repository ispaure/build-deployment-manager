"""Qt-only workflow board shared by live execution and retained results."""
from .run_state import RunState
from .workflow_presentation import duration, plan_overview

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QStackedWidget, QVBoxLayout, QWidget, QFrame, QSizePolicy, QStyle,
    QStyledItemDelegate, QStyleOptionProgressBar)
from .test_results import stage_label
from .ui_components import style_button, ActionStrip, search_shortcut


class TimingBarDelegate(QStyledItemDelegate):
    """Paint visible duration cells without allocating one QWidget per test."""
    def paint(self, painter, option, index):
        progress = index.data(Qt.ItemDataRole.UserRole)
        if progress is None:
            return super().paint(painter, option, index)
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(3, 3, -3, -3)
        bar.palette = option.palette
        bar.state = option.state
        bar.minimum, bar.maximum, bar.progress = 0, 1000, progress
        bar.textVisible = False
        option.widget.style().drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget)


class RunView(QWidget):
    review_requested = Signal()
    attention_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = RunState()
        self.rows, self.phases = {}, {}
        self.run_timing = ''
        self.selected = ''
        self.pending_refresh = self.pending_tests = False
        self.phase_log_reader = None
        self.review_available = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        heading = QLabel('Run progress & results')
        heading.setStyleSheet('font-size: 18pt; font-weight: 600;')
        layout.addWidget(heading)
        self.context = QLabel('Run source and destination will appear here.')
        self.context.setWordWrap(True)
        self.context.setAccessibleName('Source and destination of the displayed run')
        self.context.hide()  # Captured identity remains in the shared workspace.
        self.summary = QLabel('No run yet. Configure your goal and inspect the plan.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.workflow_action = QLabel('Tests and delivery progress will appear here.')
        self.workflow_action.setWordWrap(True)
        self.workflow_action.setTextFormat(Qt.TextFormat.PlainText)
        self.workflow_action.setAccessibleName('Run outcome and next action')
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
        self.destinations = QLabel()
        self.destinations.setWordWrap(True)
        self.destinations.setAccessibleName('Platform and destination outcomes')
        self.destinations.hide()
        self.plan = None
        self.progress = QProgressBar()
        self.progress.setAccessibleName('Completed workflow steps')
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.activity = ActionStrip()
        self.activity_buttons = {}
        for state, color in (('running', '#245db5'), ('queued', '#727272'),
                             ('waiting_resource', '#727272'), ('retrying', '#727272'), ('awaiting_review', '#b37c12')):
            button = style_button(QPushButton())
            button.setAutoDefault(False)
            button.setStyleSheet(button.styleSheet() + f' QPushButton {{ border-left: 4px solid {color}; }}')
            button.clicked.connect(lambda checked=False, state=state: self.inspect_activity(state))
            self.activity_buttons[state] = button
        self.overall_tests = QLabel('No individual case reports available yet.')
        self.overall_tests.setWordWrap(True)
        from .workflow_ui import WorkflowFlow
        self.flow = WorkflowFlow(self, graph_only=True)
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
        self.tabs = QTabWidget()
        inspector_layout.addWidget(self.tabs, 1)
        from .review_ui import ReviewPlanView
        self.run_choices = ReviewPlanView()
        self.run_choices.phase_selected.connect(self.select_phase)
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.pages.setAccessibleName('Workflow cards and step inspection')
        self.pages.addWidget(self.run_choices)
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
        results = QWidget()
        results_layout = QVBoxLayout(results)
        for control in (self.workflow_action, self.progress, self.activity, self.overall_tests):
            results_layout.addWidget(control)
        self.result_counts = QLabel('No test reports yet. Counts appear as tests finish.')
        self.result_counts.setWordWrap(True)
        self.result_counts.setAccessibleName('Reported test totals')
        totals = QHBoxLayout()
        self.count_cards = {}
        for state, label in (('passed', 'Passed'), ('failed', 'Failed'), ('error', 'Errors'), ('skipped', 'Skipped')):
            card = QLabel(f'<span style="font-size:24pt">0</span><br>{label}')
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setMargin(18)
            card.setFrameStyle(QLabel.Shape.StyledPanel)
            self.count_cards[state] = (card, label)
            totals.addWidget(card)
        results_layout.addLayout(totals)
        results_layout.addWidget(self.result_counts)
        self.next_action = self.step_inspector.next_action
        results_layout.addWidget(self.next_action)
        result_actions = QHBoxLayout()
        problems = self.problems_button = QPushButton('Show failed tests')
        problems.setEnabled(False)
        problems.clicked.connect(self.show_problem_tests)
        timing_button = QPushButton('See slowest tests')
        timing_button.clicked.connect(self.show_timings)
        result_actions.addWidget(problems)
        result_actions.addWidget(timing_button)
        result_actions.addStretch()
        results_layout.addLayout(result_actions)
        results_layout.addStretch()
        self.tabs.addTab(results, 'Summary')
        steps = QWidget()
        step_layout = QVBoxLayout(steps)
        self.steps = QTreeWidget()
        self.steps.setHeaderLabels(['Step', 'State / waiting reason', 'Duration', 'Kind', 'Depends on'])
        self.steps.setAccessibleName('Workflow steps and timings')
        self.steps.setColumnWidth(0, 220)
        self.steps.setColumnWidth(1, 250)
        self.steps.setAlternatingRowColors(True)
        self.steps.currentItemChanged.connect(self.select_step_item)
        # The graph is the step browser; this hidden model tracks evidence selection.
        self.steps.setParent(steps)
        self.steps.hide()
        self.detail = self.step_inspector.detail
        step_layout.addWidget(self.detail, 1)
        self.tabs.addTab(steps, 'Details')
        tests = QWidget()
        test_layout = QVBoxLayout(tests)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a test, suite or failure message…')
        self.search.setAccessibleName('Search individual tests')
        self.find_tests = search_shortcut(tests, self.search)
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        self.filter.addItems(['All tests', 'Problems', 'Passed', 'Skipped'])
        self.filter.setAccessibleName('Test outcome filter')
        self.search.textChanged.connect(self.filter_tests)
        self.filter.currentTextChanged.connect(self.filter_tests)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter)
        self.stage_filter = QComboBox()
        self.stage_filter.addItems(['All stages', 'Smoke', 'Regression', 'Extended', 'Unspecified'])
        self.stage_filter.setAccessibleName('Test execution stage filter')
        self.stage_filter.setToolTip('Execution scope reported by the runner. Unspecified means no stage was supplied.')
        self.stage_filter.currentTextChanged.connect(self.filter_tests)
        self.stage_filter.hide()
        filters.addWidget(self.stage_filter)
        self.test_matches = QLabel()
        self.test_matches.setAccessibleName('Visible test count')
        filters.addWidget(self.test_matches)
        test_layout.addLayout(filters)
        self.test_summary = QLabel('Individual cases appear when a declared JUnit report is captured.')
        self.test_summary.setWordWrap(True)
        test_layout.addWidget(self.test_summary)
        self.tests = QTreeWidget()
        self.tests.setHeaderLabels(['Test', 'Outcome', 'Duration', 'Suite / class', 'Step', 'Stage'])
        self.tests.setAccessibleName('Individual test outcomes and timings')
        self.tests.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tests.setColumnWidth(0, 240)
        self.tests.setColumnWidth(1, 80)
        self.tests.header().moveSection(5, 2)
        self.tests.headerItem().setToolTip(5, 'Execution scope: Smoke, Regression or Extended. Unspecified means the report has no stage.')
        self.tests.setColumnWidth(5, 95)
        self.tests.setColumnHidden(5, True)
        self.tests.setColumnWidth(2, 80)
        self.tests.setColumnWidth(3, 130)
        self.tests.setAlternatingRowColors(True)
        self.tests.currentItemChanged.connect(self.show_test)
        test_layout.addWidget(self.tests, 2)
        self.test_detail = QPlainTextEdit()
        self.test_detail.setReadOnly(True)
        self.test_detail.setAccessibleName('Selected test failure or skip details')
        test_layout.addWidget(self.test_detail, 1)
        self.tabs.addTab(tests, 'Tests')
        timing = QWidget()
        timing_layout = QVBoxLayout(timing)
        self.timing_summary = QLabel('Timing appears when individual test reports include durations.')
        self.timing_summary.setWordWrap(True)
        timing_layout.addWidget(self.timing_summary)
        self.timings = QTreeWidget()
        self.timings.setHeaderLabels(['Test (slowest first)', 'Duration', 'Suite / class', 'Step', 'Relative duration', 'Stage'])
        self.timings.setAccessibleName('Individual test timing profile')
        self.timings.header().setMinimumSectionSize(65)
        self.timings.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.timings.setColumnWidth(0, 240)
        self.timings.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.timings.header().moveSection(5, 2)
        self.timings.setColumnWidth(5, 95)
        self.timings.setColumnHidden(5, True)
        self.timings.setColumnWidth(2, 110)
        self.timings.setColumnWidth(3, 95)
        self.timings.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.timings.setItemDelegateForColumn(4, TimingBarDelegate(self.timings))
        timing_layout.addWidget(self.timings)
        note = QLabel('Reported test time is the sum of case durations. Parallel tests can overlap; this differs from active run time. Missing durations are excluded from averages.')
        note.setWordWrap(True)
        timing_layout.addWidget(note)
        self.tabs.addTab(timing, 'Timing')
        from .run_output_ui import RunOutputView
        self.output = RunOutputView(self)
        self.log, self.log_notice = self.output.log, self.output.notice
        log_page = self.output
        self.tabs.addTab(log_page, 'Output')
        self.tabs.addTab(self.delivery_page, 'Files and deliveries')
        # The same persistent overview/task/detail workspace owns review and run.
        # Run-only evidence supplements its inspector instead of replacing it.
        self.run_choices.inspector_tabs.addTab(self.tabs, 'Results')

    def show_results_tab(self):
        self.run_choices.inspector_tabs.setCurrentWidget(self.tabs)

    def select_group(self, key):
        self.flow.selected = ''
        self.select_phase('')
        self.tabs.setCurrentIndex(0)
        if key:
            keys = self.run_choices.flow.group_keys(key)
            priority = ('unknown', 'failed', 'error', 'timeout', 'running', 'awaiting_review', 'blocked')
            chosen = next((name for state in priority for name in keys
                if self.flow.canvas.states[name][0] == state), next(iter(keys), ''))
            if chosen:
                self.flow.select(chosen)
                self.tabs.setCurrentWidget(self.steps.parentWidget())
            self.flow.setVisible(bool(keys))

    def open_step_group(self, key):
        if key and self.run_choices.selected != key:
            # Selection is mirrored without sending it back through select_phase.
            self.run_choices.blockSignals(True)
            try:
                self.run_choices.inspect_phase(key)
            finally:
                self.run_choices.blockSignals(False)

    @property
    def facts(self):
        return self.state.facts

    @property
    def started(self):
        return self.state.started

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
        for index in range(self.delivered.topLevelItemCount()):
            row = self.delivered.topLevelItem(index)
            children = [row.child(i) for i in range(row.childCount())]
            for child in children:
                child.setHidden(child.data(0, Qt.ItemDataRole.UserRole) not in keys)
            identity = row.data(0, Qt.ItemDataRole.UserRole + 1)
            relevant = artifact_keys if identity and identity[0] == 'artifact' else keys
            row.setHidden(not any(not child.isHidden() for child in children) if children
                else row.data(0, Qt.ItemDataRole.UserRole) not in relevant)
        selected = self.delivered.currentItem()
        if selected and (selected.isHidden() or selected.parent() and selected.parent().isHidden()):
            self.delivered.setCurrentItem(None)
        self.tabs.setTabVisible(self.tabs.indexOf(self.delivery_page), any(
            not self.delivered.topLevelItem(index).isHidden() for index in range(self.delivered.topLevelItemCount())))

    def set_detail_text(self, text, key):
        self.step_inspector.set_detail_text(text, key)

    def inspect_summary_phase(self, key):
        tab = self.tabs.currentWidget()
        self.open_step_group(key)
        self.flow.select(key)
        self.restore_inspector_tab(tab)
        self.run_choices.tasks.setFocus()

    def restore_inspector_tab(self, tab):
        if self.tabs.isTabVisible(self.tabs.indexOf(tab)):
            self.tabs.setCurrentWidget(tab)
        else:
            self.tabs.setCurrentWidget(self.steps.parentWidget())

    def inspect_blocking_phase(self, key):
        self.inspect_summary_phase(key)
        self.run_choices.inspector_tabs.setCurrentWidget(self.run_choices.details_scroll)
        self.run_choices.tasks.setFocus()

    def scoped_facts(self):
        if self.plan is None:
            return {}
        grouped = self.run_choices.flow
        keys = (self.selected,) if self.selected else grouped.group_keys(grouped.selected) if grouped.has_group_scope() else self.facts
        return {key: fact for key, fact in self.facts.items() if key in keys}

    def inspect_phase_problems(self, key):
        self.inspect_summary_phase(key)
        if any(case['status'] in {'failed', 'error'} for case in self.facts.get(key, {}).get('tests', ())):
            self.search.clear()
            self.show_problem_tests()
            self.tests.setFocus()
            self.select_first_problem_test()
            self.show_results_tab()
        else:
            self.run_choices.inspector_tabs.setCurrentWidget(self.run_choices.details_scroll)

    def select_first_problem_test(self):
        for index in range(self.tests.topLevelItemCount()):
            item = self.tests.topLevelItem(index)
            if not item.isHidden():
                self.tests.setCurrentItem(item)
                self.show_test(item)
                break

    def select_step_item(self, item, previous=None):
        if item is not None and item.text(0) != self.selected:
            self.flow.select(item.text(0))
        self.show_detail(item)

    def select_phase(self, key):
        if key:
            tab = self.tabs.currentWidget()
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
        if not key:
            self.refresh_summary()

    def inspect_subtest(self, item, previous=None):
        if item is None or item.parent() is None:
            return
        case = item.data(0, Qt.ItemDataRole.UserRole + 1)
        self.test_detail.setPlainText('\n'.join(filter(None, (
            case.get('classname'), case['name'], 'Stage: ' + stage_label(case), item.text(1), item.text(2), case.get('message')))))
        self.tabs.setCurrentWidget(self.tests.parentWidget())

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
                row.setText(2, duration(fact.get('seconds')))
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
            grouped = self.run_choices.flow
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

    def append_output(self, phase, text):
        self.output.append(phase, text, selected=self.selected, keys=self.scoped_facts())

    def set_output(self, text):
        self.output.reset()
        self.append_output(None, text)
        self.refresh_output()

    def refresh_output(self):
        self.output.show_scope(selected=self.selected, keys=self.scoped_facts(), reader=self.phase_log_reader)

    def show_problem_tests(self):
        self.search.clear()
        self.stage_filter.setCurrentIndex(0)
        self.filter.setCurrentText('Problems')
        self.tabs.setCurrentWidget(self.tests.parentWidget())
        self.show_results_tab()

    def show_blocking_step(self):
        if self.blocking_key:
            self.flow.select(self.blocking_key)
            self.tabs.setCurrentWidget(self.steps.parentWidget())
            self.steps.setFocus()

    def has_problems(self):
        return self.outcome in {'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown'} or any(
            row.get('status') in {'failed', 'error', 'timeout', 'interrupted', 'unknown', 'cancelled'} or any(
                case['status'] in {'failed', 'error'} for case in row.get('tests', ()))
            for row in self.facts.values())

    def show_problems(self):
        """Leave any selected successful card and reveal the actual problem."""
        self.search.clear()
        unknown = any(row['status'] == 'unknown' for row in self.facts.values())
        failed_test = next((key for key, row in self.facts.items() if any(
            case.get('status') in {'failed', 'error'} for case in row.get('tests', ()))), '')
        if failed_test and not unknown:
            self.inspect_phase_problems(failed_test)
            return
        self.run_choices.log_reader = self.phase_log_reader
        self.run_choices.show_problems()
        self.run_choices.inspector_tabs.setCurrentWidget(self.run_choices.details_scroll)
        if not any(self.run_choices.is_problem(key) for key in self.phases):
            self.run_choices.flow.close_group()
            self.run_choices.context_info.setText(self.summary.text())
            self.run_choices.context_info.show()
            self.set_detail_text(self.summary.text(), None)

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
        self.attention_problems.setVisible(problems)
        self.attention_problems.setText('Inspect unknown outcome' if unknown else 'View problems')
        self.attention_review.setVisible(needs_review)
        dispatch = any(row['status'] == 'awaiting_review' and key in self.phases and
            (row.get('effect') or (self.phases[key].effect if self.phases[key].effect != 'inherit' else self.plan.effect)) == 'dispatch'
            for key, row in self.facts.items())
        self.attention_review.setText('Review GitHub checks…' if dispatch else 'Review delivery…')
        color = '#c54040' if problems else '#b37c12'
        self.attention.setStyleSheet('QFrame#runAttention { border: 1px solid palette(mid); '
            'border-left: 4px solid ' + color + '; border-radius: 6px; background: palette(alternate-base); }')
        self.attention.setVisible(problems or needs_review)
        self.workflow_action.setVisible(not (problems or needs_review))
        self.attention_changed.emit()

    def show_timings(self):
        self.tabs.setCurrentWidget(self.timings.parentWidget())
        self.show_results_tab()

    def reset(self, plan, previous=(), *, fields=(), capability=None, proposal=None):
        self.pending_refresh = self.pending_tests = False
        self.final_tests_signature = None
        self.plan = plan
        self.selected = ''
        self.run_choices.blockSignals(True)
        try:
            self.run_choices.reset(plan, fields, preview=False, capability=capability, proposal=proposal,
                                   summary=plan_overview(plan))
        finally:
            self.run_choices.blockSignals(False)
        self.pages.setCurrentIndex(0)
        self.delivered.clear()
        self.delivery_signature = None
        self.output.reset()
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
        self.tests.clear()
        self.detail.clear()
        self.test_detail.clear()
        self.log.clear()
        self.search.clear()
        self.filter.setCurrentIndex(0)
        self.stage_filter.setCurrentIndex(0)
        for phase in plan.phases:
            row = QTreeWidgetItem([phase.id, 'queued', '—', phase.kind, ', '.join(phase.dependencies) or '—'])
            self.steps.addTopLevelItem(row)
            self.rows[phase.id] = row
        for event in previous:
            self.update_phase(event)
        self.refresh_summary()
        self.refresh_tests()
        self.tabs.setCurrentIndex(0)
        self.refresh_inspector()
        self.refresh_output()
        self.run_choices.inspector_tabs.setCurrentWidget(self.run_choices.details_scroll)

    def update_phase(self, event, *, refresh=True):
        key = event['id']
        if key not in self.rows:
            self.rows[key] = QTreeWidgetItem([key, '', '', '', ''])
            self.steps.addTopLevelItem(self.rows[key])
        fact = self.state.update(event)
        self.rows[key].setText(1, 'reused' if fact.get('reused') else fact['status'].replace('_', ' '))
        if fact.get('recovery', {}).get('status') == 'recovered':
            self.rows[key].setText(1, 'passed after recovery')
        self.rows[key].setToolTip(1, fact.get('reason') or fact.get('error', ''))
        if event['status'] != 'running' and 'seconds' in event:
            self.rows[key].setText(2, duration(event['seconds']))
        self.pending_refresh = True
        self.pending_tests |= 'tests' in event or 'live_tests' in event
        if refresh:
            self.flush_updates()

    def flush_updates(self):
        if not self.pending_refresh:
            return
        self.pending_refresh = False
        self.refresh_summary()
        self.flow.set_facts(self.live_facts())
        self.refresh_inspector()
        if self.pending_tests:
            self.pending_tests = False
            self.refresh_tests()

    def tick(self):
        if self.pending_refresh:
            self.flush_updates()
            return
        for key, started in self.started.items():
            elapsed = duration(self.state.clock() - started)
            self.rows[key].setText(2, elapsed)
            if key in self.flow.canvas.cards:
                self.flow.canvas.cards[key][1].setText('Running · ' + elapsed)
        facts = self.live_facts()
        self.flow.set_facts(facts)
        self.run_choices.set_facts(facts)
        self.refresh_inspector()

    def refresh_summary(self):
        self.run_choices.log_reader = self.phase_log_reader
        terminal = {'passed', 'failed', 'error', 'skipped', 'cancelled', 'timeout', 'interrupted', 'unknown'}
        counts = {}
        for fact in self.facts.values():
            state = fact['status']
            counts[state] = counts.get(state, 0) + 1
        done = sum(value for key, value in counts.items() if key in terminal)
        self.progress.setRange(0, max(1, len(self.rows)))
        self.progress.setValue(done)
        self.progress.setFormat(f'{done} / {len(self.rows)} steps finished')
        from .workflow_presentation import display_states
        visible_counts = {}
        for state, _ in display_states(self.plan, self.facts).values() if self.plan else ():
            visible_counts[state] = visible_counts.get(state, 0) + 1
        text = ' · '.join(f'{value} {key.replace("_", " ")}' for key, value in visible_counts.items()) or 'No steps'
        prefix = ('Workflow: ' + self.outcome.replace('_', ' ') + ' · ') if self.outcome else ''
        self.summary.setText(prefix + f'{done} / {len(self.rows)} steps finished · ' + text + self.run_timing)
        activity_names = {'running': 'Running', 'queued': 'Queued',
            'waiting_resource': 'Waiting for capacity', 'retrying': 'Waiting to reconnect', 'awaiting_review': 'Needs approval'}
        for button in self.activity_buttons.values():
            self.activity.grid.removeWidget(button)
        active = []
        for state, button in self.activity_buttons.items():
            count = visible_counts.get(state, 0)
            button.setText(activity_names[state] + ' · ' + str(count))
            button.setVisible(bool(count) and not self.outcome)
            button.setEnabled(not self.cancelling)
            if count and not self.outcome:
                active.append(button)
        self.activity.buttons, self.activity.columns = active, 0
        self.activity.reflow()
        self.activity.setVisible(not self.outcome and any(visible_counts.get(state) for state in activity_names))
        if self.cancelling:
            self.summary.setText('Stopping… · ' + text + self.run_timing)
        self.progress.setAccessibleDescription(self.summary.text())
        self.run_choices.set_facts(self.live_facts())
        cases = [case for fact in self.facts.values() for case in fact.get('tests', ())]
        problems = sum(case['status'] in {'failed', 'error'} for case in cases)
        self.overall_tests.setText(f'{len(cases)} reported test cases · {problems} problems' if cases
            else 'No individual case reports available yet. Step outcomes remain available.')
        interim = sum(len(fact.get('live_tests', ())) for fact in self.facts.values())
        if interim:
            self.overall_tests.setText(f'{interim} interim test results · suites still running' +
                (f' · {len(cases)} final results' if cases else ''))
        self.overall_tests.setVisible(bool(cases or interim))
        if self.outcome == 'unknown' or counts.get('unknown'):
            action = 'An external action has an unknown outcome. Check its provider status before retrying; the manager will not repeat it automatically.'
        elif self.outcome == 'awaiting_review' or counts.get('awaiting_review'):
            action = ('GitHub checks are waiting for approval to start. Review the workflow and exact source before continuing.'
                if any(fact['status']=='awaiting_review' and (fact.get('effect') or
                    (self.phases[key].effect if self.phases[key].effect != 'inherit' else self.plan.effect)) == 'dispatch'
                    for key, fact in self.facts.items() if key in self.phases)
                else 'Eligible actions need approval. Use the review action below to inspect prepared files, exact source and destinations. Independent blocked branches remain separate.')
        elif self.outcome in {'failed', 'error', 'cancelled', 'interrupted'}:
            action = 'This run did not finish successfully. Use View problems, or open a workflow card and select a step to inspect the reason.'
        elif self.outcome == 'passed':
            destinations = getattr(self.plan, 'journey', {}).get('destinations', {}) if self.plan else {}
            delivered = sum(all(self.facts.get(key, {}).get('status') == 'passed' for key in row['steps'])
                for row in destinations.values())
            files = len({(a['path'], a.get('sha256', '')) for fact in self.facts.values()
                         for a in fact.get('artifacts', ())})
            action = f'{delivered} of {len(destinations)} destinations delivered' if destinations else 'Completed'
            if files:
                action += f' · {files} retained file' + ('s' if files != 1 else '')
        elif self.outcome:
            action = 'Run finished. Check Tests for individual outcomes and Timing for the slowest tests. Open another run with the + tab button.'
        else:
            action = 'Work is in progress. Test totals update as reports arrive. Delivery requires a separate approval.'
        self.workflow_action.setText(action)
        self.next_action.setText(action)
        if self.plan and getattr(self.plan, 'journey', {}):
            from .journeys import outcomes
            self.destinations.setText('\n'.join(label + ': ' + state.replace('_', ' ')
                for label, state in outcomes(self.plan, self.facts.values())))
        else:
            self.destinations.clear()
        self.refresh_attention()
        self.refresh_delivered()

    def inspect_activity(self, state):
        from .workflow_presentation import display_states
        key = next((key for key, (value, _) in display_states(self.plan, self.facts).items()
                    if value == state), None)
        if key:
            self.inspect_blocking_phase(key)

    def cancellation_requested(self):
        self.state.cancelling = True
        self.refresh_summary()

    def refresh_delivered(self):
        from .journeys import outcomes
        from pathlib import PurePath
        if not self.plan:
            return
        signature = tuple((key, fact['status'], tuple((a['path'], a.get('sha256', ''))
            for a in fact.get('artifacts', ()))) for key, fact in self.facts.items())
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
        states = dict(outcomes(self.plan, self.facts.values())) if journey else {}
        labels = {'passed': 'Delivered', 'awaiting_review': 'Needs approval', 'unknown': 'Unknown outcome',
                  'skipped': 'Not delivered', 'queued': 'Not started'}
        for destination in journey.get('destinations', {}).values():
            state = states[destination['identity']]
            row = QTreeWidgetItem([destination['identity'], labels.get(state, state.replace('_', ' ').capitalize()), ''])
            row.setToolTip(0, destination['identity'])
            icon = (QStyle.StandardPixmap.SP_DialogApplyButton if state == 'passed' else
                QStyle.StandardPixmap.SP_MessageBoxCritical if state in {'unknown', 'failed', 'error', 'timeout'}
                else QStyle.StandardPixmap.SP_MessageBoxWarning)
            row.setIcon(1, self.style().standardIcon(icon))
            priority = ('unknown', 'failed', 'error', 'timeout', 'interrupted', 'cancelled', 'awaiting_review', 'running')
            key = next((key for state in priority for key in destination['steps']
                if self.facts.get(key, {}).get('status') == state), destination['steps'][0])
            row.setData(0, Qt.ItemDataRole.UserRole, key)
            row.setData(0, Qt.ItemDataRole.UserRole + 1, ('destination', destination['identity']))
            for key in destination['steps']:
                child = QTreeWidgetItem([getattr(self.phases[key], 'label', '') or key,
                    self.facts.get(key, {}).get('status', 'queued').replace('_', ' '), ''])
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, ('step', key))
                row.addChild(child)
            self.delivered.addTopLevelItem(row)
        for key, fact in self.facts.items():
            for artifact in fact.get('artifacts', ()):
                path = artifact['path']
                name = PurePath(artifact.get('original_path') or path).name
                row = QTreeWidgetItem([name, 'Retained file', path])
                row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                row.setToolTip(0, 'SHA-256: ' + artifact.get('sha256', 'Not recorded'))
                row.setToolTip(2, path)
                row.setData(0, Qt.ItemDataRole.UserRole, key)
                row.setData(0, Qt.ItemDataRole.UserRole + 1, ('artifact', key, path))
                self.delivered.addTopLevelItem(row)
        self.tabs.setTabVisible(self.tabs.indexOf(self.delivery_page), bool(self.delivered.topLevelItemCount()))
        for index in range(self.delivered.topLevelItemCount()):
            row = self.delivered.topLevelItem(index)
            row.setExpanded(row.data(0, Qt.ItemDataRole.UserRole + 1) in expanded)
            for item in (row, *(row.child(i) for i in range(row.childCount()))):
                if identity and item.data(0, Qt.ItemDataRole.UserRole + 1) == identity:
                    self.delivered.setCurrentItem(item)
        self.delivered.verticalScrollBar().setValue(scroll)
        self.filter_delivered()

    def inspect_delivered(self, item, column=0):
        if item:
            self.inspect_blocking_phase(item.data(0, Qt.ItemDataRole.UserRole))
            self.tabs.setCurrentWidget(self.steps.parentWidget())
            self.show_results_tab()

    def complete(self, report):
        self.state.complete(report['status'])
        self.run_timing = ' · Active time: ' + duration(report.get('seconds'))
        if report.get('attempts'):
            self.run_timing += f' across {len(report["attempts"])} attempt(s)'
        self.flow.set_facts(self.facts)
        self.refresh_summary()
        self.refresh_inspector()


    def unverified(self, reason):
        self.state.complete('failed')
        self.run_timing = ' · Result could not be verified: ' + reason
        for key, fact in list(self.facts.items()):
            if fact['status'] == 'running':
                self.update_phase(dict(id=key, status='unknown', reason='Process ended without a verified result.'))
        self.refresh_summary()

    def show_detail(self, item, previous=None):
        if item is None:
            return
        key = item.text(0)
        fact, phase = self.facts.get(key, {}), self.phases.get(key)
        from .workflow_presentation import display_states, state_label, step_time
        state, reason = display_states(self.plan, self.facts)[key]
        lines = [key, 'State: ' + state_label(state)]
        if reason:
            lines.append(reason)
        elapsed = step_time(self.live_facts().get(key, fact), state)
        if elapsed:
            lines.append('Step duration: ' + elapsed)
        for field in ('reason', 'error', 'summary', 'cleanup_error'):
            if fact.get(field):
                lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
        problems = [case for case in fact.get('tests', []) if case['status'] in {'failed', 'error'}]
        for case in problems[:3]:
            lines += ['', case['name'] + ': ' + case['status'], case['message']]
        if phase:
            from .workflow_presentation import title
            lines += ['', f'Gate: {"required" if phase.required else "optional"}',
                      'Dependencies: ' + (', '.join(title(self.phases[name]) for name in phase.dependencies) or 'none'),
                      'Timeout: ' + duration(phase.timeout)]
            if getattr(phase, 'waits_for', ()):
                lines.append('Scheduling only: wait for completion of ' + ', '.join(phase.waits_for))
        if fact.get('log'):
            lines.append('Log in results folder: ' + fact['log'])
        for artifact in fact.get('artifacts', []):
            lines += ['Artifact: ' + artifact['path'], 'SHA-256: ' + artifact['sha256']]
        grouped = self.run_choices.flow
        if grouped.has_group_scope():
            lines += ['', grouped.group_context()]
        # Caller supplies redacted plan data; report facts are redacted by executor.
        self.set_detail_text('\n'.join(lines), key)

    def refresh_tests(self):
        scope = self.scoped_facts()
        signature = tuple((key, tuple((case.get('name'), case.get('status'),
                                      case.get('seconds'), case.get('message'),
                                      case.get('suite'), case.get('classname'), case.get('stage'))
                                     for case in fact.get('tests', ())))
                          for key, fact in scope.items())
        interim = sum(len(fact.get('live_tests', ())) for fact in scope.values())
        if getattr(self, 'final_tests_signature', None) == signature:
            # Interim case snapshots do not change final rows or timing bars.
            # Rebuilding thousands of native items here stalls resize/input.
            if interim:
                final = sum(len(fact.get('tests', ())) for fact in scope.values())
                self.result_counts.setText(f'{final} final test results · {interim} interim results\n'
                    'Expand the execution step above to inspect live reports.')
            return
        self.final_tests_signature = signature
        current = self.tests.currentItem()
        previous = (current.text(4), current.data(0, Qt.ItemDataRole.UserRole)) if current else None
        self.test_detail.clear()
        self.tests.clear()
        counts = {}
        measured = []
        missing = 0
        for key, fact in self.scoped_facts().items():
            for case in fact.get('tests', []):
                if case.get('seconds') is None:
                    missing += 1
                else:
                    measured.append((case['seconds'], case, key))
                status = case['status']
                counts[status] = counts.get(status, 0) + 1
                item = QTreeWidgetItem([case['name'], status, duration(case['seconds']),
                                       ' / '.join(filter(None, [case['suite'], case['classname']])), key, stage_label(case)])
                item.setData(0, Qt.ItemDataRole.UserRole, case)
                self.tests.addTopLevelItem(item)
                if previous == (key, case):
                    self.tests.setCurrentItem(item)
        self.test_summary.setText(' · '.join(f'{value} {key}' for key, value in counts.items())
                                 if counts else 'No individual case report supplied. Step results remain available.')
        self.result_counts.setText(f'{sum(counts.values())} reported tests\n' + self.test_summary.text())
        interim = sum(len(fact.get('live_tests', ())) for fact in self.scoped_facts().values())
        if interim:
            self.result_counts.setText(f'{sum(counts.values())} final test results · {interim} interim results\n'
                'Expand the execution step above to inspect live reports.')
            self.test_summary.setText('Interim reports are shown under the execution step; final outcomes appear here when the suite finishes.')
        for state, (card, label) in self.count_cards.items():
            value = counts.get(state, 0) if counts else '—'
            card.setText(f'<span style="font-size:24pt">{value}</span><br>{label}')
            card.setAccessibleName(f'{value} {label.lower()} tests' if counts else label + ' count not reported yet')
        self.problems_button.setEnabled(bool(counts.get('failed') or counts.get('error')))
        self.timings.clear()
        longest = max((row[0] for row in measured), default=0)
        for seconds, case, key in sorted(measured, key=lambda row: row[0], reverse=True):
            item = QTreeWidgetItem([case['name'], duration(seconds),
                ' / '.join(filter(None, [case['suite'], case['classname']])), key, '', stage_label(case)])
            self.timings.addTopLevelItem(item)
            item.setData(4, Qt.ItemDataRole.UserRole, round(1000 * seconds / longest) if longest else 0)
            item.setData(4, Qt.ItemDataRole.AccessibleTextRole, case['name'] + ': ' + duration(seconds))
            item.setToolTip(4, 'Relative to the slowest reported test: ' + duration(longest))
        if measured:
            from statistics import median
            values = [row[0] for row in measured]
            self.timing_summary.setText(f'{len(values)} timed tests · {missing} without duration\n'
                f'Total reported test time: {duration(sum(values))} · Average: {duration(sum(values)/len(values))} · Median: {duration(median(values))}')
        else:
            self.timing_summary.setText(f'No individual test durations reported. {missing} tests without duration. Step durations are available in Details.')
        classified = any(case.get('stage') for fact in scope.values() for case in fact.get('tests', ()))
        self.tests.setColumnHidden(5, not classified)
        self.timings.setColumnHidden(5, not classified)
        self.stage_filter.setVisible(classified)
        if not classified:
            self.stage_filter.setCurrentIndex(0)
        self.tests.setColumnHidden(4, bool(self.selected))
        self.timings.setColumnHidden(3, bool(self.selected))
        self.filter_tests()
        current = self.substeps.currentItem()
        if current is not None and current.parent() is not None and self.tabs.currentWidget() == self.tests.parentWidget():
            self.inspect_subtest(current)

    def filter_tests(self, *_):
        query, choice = self.search.text().casefold(), self.filter.currentText()
        shown = 0
        stage = self.stage_filter.currentText()
        for index in range(self.tests.topLevelItemCount()):
            item = self.tests.topLevelItem(index)
            case = item.data(0, Qt.ItemDataRole.UserRole)
            text = ' '.join(str(value) for value in case.values()).casefold()
            visible = (not query or query in text) and (
                choice == 'All tests' or choice == 'Problems' and case['status'] in {'failed', 'error'}
                or choice == 'Passed' and case['status'] == 'passed'
                or choice == 'Skipped' and case['status'] == 'skipped')
            visible = visible and (stage == 'All stages' or stage_label(case) == stage)
            item.setHidden(not visible)
            shown += int(visible)
        active = query or choice != 'All tests' or stage != 'All stages'
        self.test_matches.setText(f'{shown} / {self.tests.topLevelItemCount()} shown' if active else '')
        current = self.tests.currentItem()
        if current is not None and current.isHidden():
            self.tests.setCurrentItem(None)
            self.test_detail.clear()

    def show_test(self, item, previous=None):
        if item:
            case = item.data(0, Qt.ItemDataRole.UserRole)
            self.test_detail.setPlainText(f'{case["classname"]}.{case["name"]}\n'
                                          f'{case["status"]} · {duration(case["seconds"])} · Stage: {stage_label(case)}\n\n{case["message"]}')
