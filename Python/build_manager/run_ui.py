"""Qt-only workflow board shared by live execution and retained results."""
import time
from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QSplitter, QVBoxLayout, QWidget, QFrame, QSizePolicy, QStyle)
from .ui_components import style_button, ActionStrip, search_shortcut


def duration(seconds):
    if seconds is None:
        return '—'
    return f'{seconds:.2f}s' if seconds < 60 else f'{int(seconds // 60)}m {seconds % 60:.1f}s'


def plan_overview(plan):
    lines = [f'{plan.project} · {plan.operation}', f'Runs on: {plan.backend}',
             f'Workflow effect: {plan.effect}', '', 'Source:']
    if plan.adapter.get('test_suite'):
        lines.insert(3, 'Selected suite: ' + plan.adapter['test_suite'])
    journey = getattr(plan, 'journey', {})
    if journey:
        lines += ['', 'Selected platforms: ' + ', '.join(journey['platforms']),
                  'Each destination requires its declared platform validation; independent branches can proceed separately.',
                  'Delivery pauses for artifact-specific review. Independent approved branches may overlap.',
                  f'At most {plan.max_workers} steps run at once, subject to shared resources.']
        for name, row in journey['destinations'].items():
            required = ', '.join(row.get('platforms', list(journey['platforms'])))
            lines.append('Destination ' + name + ': ' + row['identity'] + ' · requires: ' + required + ' · ' + ', '.join(row['steps']))
    def describe(value, indent='  '):
        rows = []
        for key, item in value.items():
            label = key.replace('_', ' ').capitalize()
            if isinstance(item, dict):
                rows += [indent + label + ':'] + describe(item, indent + '  ')
            else:
                text = ', '.join(str(part) for part in item) if isinstance(item, (list, tuple)) else str(item)
                rows.append(indent + label + ': ' + text)
        return rows or [indent + 'None declared']
    lines += describe(plan.source)
    lines += ['', 'Settings and declared destinations:', *describe(plan.settings),
              '', 'Steps in execution order (dependencies determine overlap):']
    for number, phase in enumerate(plan.phases, 1):
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        lines += [f'{number}. {phase.id} · {phase.kind} · {effect}',
                  f'   {"Required" if phase.required else "Optional"}; timeout {duration(phase.timeout)}; '
                  f'depends on: {", ".join(phase.dependencies) or "none"}',
                  '   ' + ('External action: explicit review required.' if effect in {'upload', 'deploy', 'publish','dispatch'}
                            else 'Preparation / local execution.')]
    return '\n'.join(lines)


class RunView(QWidget):
    review_requested = Signal()
    attention_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.facts, self.started, self.phases = {}, {}, {}, {}
        self.run_timing = ''
        self.outcome = ''
        self.cancelling = False
        self.selected = ''
        self.output_lines = deque(maxlen=6000)
        self.phase_log_reader = None
        self.review_available = False
        layout = QVBoxLayout(self)
        self.context = QLabel('Run source and destination will appear here.')
        self.context.setWordWrap(True)
        self.context.setAccessibleName('Source and destination of the displayed run')
        layout.addWidget(self.context)
        self.summary = QLabel('No run yet. Configure your goal and inspect the plan.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.workflow_action = QLabel('Tests and delivery progress will appear here.')
        self.workflow_action.setWordWrap(True)
        self.workflow_action.setTextFormat(Qt.TextFormat.PlainText)
        self.workflow_action.setAccessibleName('Run outcome and next action')
        layout.addWidget(self.workflow_action)
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
        layout.addWidget(self.progress)
        self.activity = ActionStrip()
        self.activity_buttons = {}
        for state, color in (('running', '#245db5'), ('queued', '#727272'),
                             ('waiting_resource', '#727272'), ('awaiting_review', '#b37c12')):
            button = style_button(QPushButton())
            button.setAutoDefault(False)
            button.setStyleSheet(button.styleSheet() + f' QPushButton {{ border-left: 4px solid {color}; }}')
            button.clicked.connect(lambda checked=False, state=state: self.inspect_activity(state))
            self.activity_buttons[state] = button
        layout.addWidget(self.activity)
        self.overall_tests = QLabel('No individual case reports available yet.')
        self.overall_tests.setWordWrap(True)
        layout.addWidget(self.overall_tests)
        from .workflow_ui import WorkflowFlow
        self.flow = WorkflowFlow()
        self.flow.phase_selected.connect(self.select_phase)
        inspector = QWidget()
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(4, 0, 0, 0)
        self.selection_heading = QLabel('Whole workflow')
        self.selection_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_heading.setWordWrap(True)
        self.selection_heading.setStyleSheet('font-weight: 600; font-size: 14pt;')
        self.selection_info = QLabel('Select a workflow card to inspect its progress, tests, timing and output.')
        self.selection_info.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_info.setWordWrap(True)
        inspector_layout.addWidget(self.selection_heading)
        inspector_layout.addWidget(self.selection_info)
        self.blocking_step = style_button(QPushButton('View blocking step'))
        self.blocking_step.hide()
        self.blocking_key = ''
        self.blocking_step.clicked.connect(self.show_blocking_step)
        inspector_layout.addWidget(self.blocking_step)
        self.tabs = QTabWidget()
        inspector_layout.addWidget(self.tabs, 1)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.flow)
        self.splitter.addWidget(inspector)
        self.splitter.setSizes([490, 590])
        self.splitter.setChildrenCollapsible(False)
        from .plan_summary_ui import PlanSummaryView
        self.run_choices = PlanSummaryView()
        self.run_choices.phase_selected.connect(self.inspect_summary_phase)
        self.run_choices.blocker_selected.connect(self.inspect_blocking_phase)
        self.pages = QTabWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.pages.setAccessibleName('Run summary and detailed results')
        self.pages.addTab(self.run_choices, 'Run summary')
        self.pages.addTab(self.splitter, 'Results and exact steps')
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
        self.pages.addTab(self.delivery_page, 'Deliveries and files')
        self.pages.setTabVisible(2, False)
        layout.addWidget(self.pages, 1)
        results = QWidget()
        results_layout = QVBoxLayout(results)
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
        self.next_action = QLabel()
        self.next_action.setWordWrap(True)
        self.next_action.setTextFormat(Qt.TextFormat.PlainText)
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
        self.tabs.addTab(results, 'Results')
        steps = QWidget()
        step_layout = QVBoxLayout(steps)
        self.steps = QTreeWidget()
        self.steps.setHeaderLabels(['Step', 'State / waiting reason', 'Duration', 'Kind', 'Depends on'])
        self.steps.setAccessibleName('Workflow steps and timings')
        self.steps.setColumnWidth(0, 220)
        self.steps.setColumnWidth(1, 250)
        self.steps.setAlternatingRowColors(True)
        self.steps.currentItemChanged.connect(self.select_step_item)
        step_layout.addWidget(self.steps, 2)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName('Selected step details and evidence')
        step_layout.addWidget(self.detail, 1)
        self.tabs.addTab(steps, 'Step details')
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
        test_layout.addLayout(filters)
        self.test_summary = QLabel('Individual cases appear when a declared JUnit report is captured.')
        self.test_summary.setWordWrap(True)
        test_layout.addWidget(self.test_summary)
        self.tests = QTreeWidget()
        self.tests.setHeaderLabels(['Test', 'Outcome', 'Duration', 'Suite / class', 'Step'])
        self.tests.setAccessibleName('Individual test outcomes and timings')
        self.tests.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
        self.timings.setHeaderLabels(['Test (slowest first)', 'Duration', 'Suite / class', 'Step', 'Relative duration'])
        self.timings.setAccessibleName('Individual test timing profile')
        self.timings.header().setMinimumSectionSize(65)
        self.timings.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.timings.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.timings.setColumnWidth(2, 110)
        self.timings.setColumnWidth(3, 95)
        self.timings.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        timing_layout.addWidget(self.timings)
        note = QLabel('Reported test time is the sum of case durations. Parallel tests can overlap; this differs from active run time. Missing durations are excluded from averages.')
        note.setWordWrap(True)
        timing_layout.addWidget(note)
        self.tabs.addTab(timing, 'Timing')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setAccessibleName('Live redacted execution output')
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        self.log_notice = QLabel('Output for the whole workflow.')
        self.log_notice.setWordWrap(True)
        log_layout.addWidget(self.log_notice)
        log_layout.addWidget(self.log)
        self.tabs.addTab(log_page, 'Output')

    def inspect_summary_phase(self, key):
        self.pages.setCurrentIndex(1)
        self.flow.select(key)
        self.flow.browser.setFocus()

    def inspect_blocking_phase(self, key):
        self.inspect_summary_phase(key)
        self.tabs.setCurrentWidget(self.steps.parentWidget())
        self.steps.setFocus()

    def scoped_facts(self):
        return {key: fact for key, fact in self.facts.items() if not self.selected or key == self.selected}

    def select_step_item(self, item, previous=None):
        if item is not None and item.text(0) != self.selected:
            self.flow.select(item.text(0))
        self.show_detail(item)

    def select_phase(self, key):
        self.selected = key
        if key:
            self.steps.setCurrentItem(self.rows.get(key))
        else:
            self.steps.setCurrentItem(None)
            self.detail.clear()
        for name, row in self.rows.items():
            row.setHidden(bool(key) and name != key)
        self.refresh_inspector()
        self.refresh_tests()
        self.refresh_output()
        if not key:
            self.refresh_summary()

    def refresh_inspector(self):
        from .workflow_ui import blocking_prerequisite
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, self.selected) if self.plan else ''
        self.blocking_step.setVisible(bool(self.blocking_key))
        if not self.selected:
            self.selection_heading.setText('Whole workflow')
            self.selection_info.setText('Totals below include every step. Select a card on the left for that step’s details.' +
                ('\n' + self.destinations.text() if self.destinations.text() else ''))
            return
        from .workflow_ui import title, effect_label
        phase = self.phases[self.selected]
        fact = self.facts.get(self.selected, {})
        state, reason = self.flow.canvas.states.get(self.selected, ('queued', ''))
        self.selection_heading.setText(title(phase))
        dependencies = ', '.join(title(self.phases[key]) for key in phase.dependencies) or 'None'
        text = f'{effect_label(phase, self.plan)} · {state.replace("_", " ")}\nPrerequisites: {dependencies}'
        if reason:
            text += '\n' + reason
        if fact.get('seconds') is not None:
            text += '\nStep duration: ' + duration(fact['seconds'])
        elif self.selected in self.started:
            text += '\nRunning for: ' + duration(time.monotonic() - self.started[self.selected])
        if getattr(phase, 'waits_for', ()):
            text += '\nWaits for completion (success not required): ' + ', '.join(phase.waits_for)
        if phase.resources:
            from .resources import resource_details
            text += '\n' + '\n'.join(resource_details(self.plan, self.selected))
        for row in getattr(self.plan, 'journey', {}).get('destinations', {}).values():
            if self.selected in row['steps']:
                text += '\nDestination: ' + row['identity']
        self.selection_info.setText(text)
        if state in {'blocked', 'skipped'}:
            self.next_action.setText('This step will not run. ' + reason + '\nSelect its prerequisite cards to inspect the cause.')
        elif state == 'waiting_resource':
            self.next_action.setText(reason + '\nOther independent platform steps can continue.')
        elif state == 'running':
            self.next_action.setText('This step is running. Reports appear after capture; Output shows its current messages.')
        elif state == 'passed':
            self.next_action.setText('This step passed. Results and timing below belong to this card. Other branches may still be running.')
        elif state in {'failed', 'error', 'timeout'}:
            self.next_action.setText('This step failed. Inspect Tests for failures or Step details and Output for the reason.')
        elif state == 'awaiting_review':
            self.next_action.setText('This step needs your approval. Use Review and continue below the workflow to inspect the exact action before it starts.')
        elif state == 'unknown':
            self.next_action.setText('This step has an unknown outcome. Check its provider status before retrying; it will not repeat automatically.')
        else:
            self.next_action.setText(reason or 'This step has not produced a report. Inspect Step details for its current state.')
        self.show_detail(self.rows.get(self.selected))

    def append_output(self, phase, text):
        for line in text.splitlines():
            self.output_lines.append((phase, line))
            if not self.selected or phase == self.selected:
                self.log.appendPlainText(('[' + phase + '] ' if phase and not self.selected else '') + line)

    def set_output(self, text):
        self.output_lines.clear()
        self.append_output(None, text)
        self.refresh_output()

    def refresh_output(self):
        lines = [('[' + key + '] ' if key and not self.selected else '') + text
                 for key, text in self.output_lines if not self.selected or key == self.selected]
        self.log_notice.setText('Output for the selected card. Unattributed runner messages appear in Whole workflow.'
                               if self.selected else 'Output for the whole workflow.')
        if self.selected and not lines and self.phase_log_reader:
            try:
                lines = [self.phase_log_reader(self.selected)]
            except (OSError, ValueError):
                lines = []
        self.log.setPlainText('\n'.join(lines) if any(lines) else 'No captured output for this selection yet. Retained log paths appear in Step details.')

    def show_problem_tests(self):
        self.pages.setCurrentIndex(1)
        self.filter.setCurrentText('Problems')
        self.tabs.setCurrentWidget(self.tests.parentWidget())

    def show_blocking_step(self):
        if self.blocking_key:
            self.pages.setCurrentIndex(1)
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
        self.pages.setCurrentIndex(1)
        self.search.clear()
        self.flow.select('')
        unknown = next((key for key, row in self.facts.items() if row['status'] == 'unknown'), None)
        cases = any(case['status'] in {'failed', 'error'}
                    for row in self.facts.values() for case in row.get('tests', ()))
        if cases and not unknown:
            self.show_problem_tests()
            self.tests.setFocus()
            return
        key = unknown or next((key for key, row in self.facts.items()
            if row['status'] in {'failed', 'error', 'timeout', 'cancelled', 'interrupted'}), None)
        if key:
            self.flow.select(key)
        else:
            self.detail.setPlainText(self.summary.text())
        self.tabs.setCurrentWidget(self.steps.parentWidget())
        self.steps.setFocus()

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
            from .workflow_ui import title
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
        self.pages.setCurrentIndex(1)
        self.tabs.setCurrentWidget(self.timings.parentWidget())

    def reset(self, plan, previous=(), *, fields=(), capability=None, proposal=None):
        self.plan = plan
        self.selected = ''
        self.run_choices.reset(plan, fields, preview=False, capability=capability, proposal=proposal)
        self.pages.setCurrentIndex(0)
        self.delivered.clear()
        self.delivery_signature = None
        self.pages.setTabVisible(2, False)
        self.output_lines.clear()
        self.flow.reset(plan)
        self.rows, self.facts, self.started = {}, {}, {}
        self.phases = {phase.id: phase for phase in plan.phases}
        from .plan_summary import captured_choices
        source = captured_choices(plan)[0][1]
        self.context.setText(f'{plan.project} · {plan.operation} · ' + source.replace('\n', ' · '))
        self.context.setToolTip(source)
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.run_timing = ''
        self.outcome = ''
        self.cancelling = False
        self.set_review_available(False)
        self.steps.clear()
        self.tests.clear()
        self.detail.clear()
        self.test_detail.clear()
        self.log.clear()
        self.search.clear()
        self.filter.setCurrentIndex(0)
        for phase in plan.phases:
            row = QTreeWidgetItem([phase.id, 'queued', '—', phase.kind, ', '.join(phase.dependencies) or '—'])
            self.steps.addTopLevelItem(row)
            self.rows[phase.id] = row
            self.facts[phase.id] = dict(id=phase.id, status='queued')
        for event in previous:
            self.update_phase(event)
        self.refresh_summary()
        self.refresh_tests()
        self.tabs.setCurrentIndex(0)
        self.refresh_inspector()
        self.refresh_output()

    def update_phase(self, event):
        key = event['id']
        if key not in self.rows:
            self.rows[key] = QTreeWidgetItem([key, '', '', '', ''])
            self.steps.addTopLevelItem(self.rows[key])
        if event['status'] != 'waiting_resource':
            event = dict(event, resource='', reason=event.get('reason', ''))
        self.facts.setdefault(key, {}).update(event)
        self.rows[key].setText(1, event['status'].replace('_', ' '))
        self.rows[key].setToolTip(1, event.get('reason') or event.get('error', ''))
        if event['status'] == 'running':
            self.started.setdefault(key, time.monotonic())
        else:
            self.started.pop(key, None)
            if 'seconds' in event:
                self.rows[key].setText(2, duration(event['seconds']))
        self.refresh_summary()
        self.flow.set_facts(self.facts)
        self.refresh_inspector()
        if self.steps.currentItem() == self.rows[key]:
            self.show_detail(self.rows[key])
        if 'tests' in event:
            self.refresh_tests()

    def tick(self):
        for key, started in self.started.items():
            elapsed = duration(time.monotonic() - started)
            self.rows[key].setText(2, elapsed)
            if key in self.flow.canvas.cards:
                self.flow.canvas.cards[key][1].setText('Running · ' + elapsed)
        self.run_choices.set_facts({key: dict(fact, seconds=time.monotonic() - self.started[key])
            if key in self.started else fact for key, fact in self.facts.items()})
        self.refresh_inspector()

    def refresh_summary(self):
        terminal = {'passed', 'failed', 'error', 'skipped', 'cancelled', 'timeout', 'interrupted', 'unknown'}
        counts = {}
        for fact in self.facts.values():
            state = fact['status']
            counts[state] = counts.get(state, 0) + 1
        done = sum(value for key, value in counts.items() if key in terminal)
        self.progress.setRange(0, max(1, len(self.rows)))
        self.progress.setValue(done)
        self.progress.setFormat(f'{done} / {len(self.rows)} steps finished')
        from .workflow_ui import display_states
        visible_counts = {}
        for state, _ in display_states(self.plan, self.facts).values() if self.plan else ():
            visible_counts[state] = visible_counts.get(state, 0) + 1
        text = ' · '.join(f'{value} {key.replace("_", " ")}' for key, value in visible_counts.items()) or 'No steps'
        prefix = ('Workflow: ' + self.outcome.replace('_', ' ') + ' · ') if self.outcome else ''
        self.summary.setText(prefix + text + self.run_timing)
        activity_names = {'running': 'Running', 'queued': 'Queued',
            'waiting_resource': 'Waiting for capacity', 'awaiting_review': 'Needs approval'}
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
        self.run_choices.set_facts(self.facts)
        cases = [case for fact in self.facts.values() for case in fact.get('tests', ())]
        problems = sum(case['status'] in {'failed', 'error'} for case in cases)
        self.overall_tests.setText(f'{len(cases)} reported test cases · {problems} problems' if cases
            else 'No individual case reports available yet. Step outcomes remain available.')
        self.overall_tests.setVisible(bool(cases))
        if self.outcome == 'unknown' or counts.get('unknown'):
            action = 'An external action has an unknown outcome. Check its provider status before retrying; the manager will not repeat it automatically.'
        elif self.outcome == 'awaiting_review' or counts.get('awaiting_review'):
            action = ('GitHub checks are waiting for approval to start. Review the workflow and exact source before continuing.'
                if any(fact['status']=='awaiting_review' and (fact.get('effect') or
                    (self.phases[key].effect if self.phases[key].effect != 'inherit' else self.plan.effect)) == 'dispatch'
                    for key, fact in self.facts.items() if key in self.phases)
                else 'Eligible actions need approval. Use the review action below to inspect prepared files, exact source and destinations. Independent blocked branches remain separate.')
        elif self.outcome in {'failed', 'error', 'cancelled', 'interrupted'}:
            action = 'This run did not finish successfully. Open Results and exact steps, then Tests → Problems or Step details for the reason.'
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
            action = 'Run finished. Check Tests for individual outcomes and Timing for the slowest tests. Start another run from New run.'
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
        from .workflow_ui import display_states
        key = next((key for key, (value, _) in display_states(self.plan, self.facts).items()
                    if value == state), None)
        if key:
            self.inspect_blocking_phase(key)

    def cancellation_requested(self):
        self.cancelling = True
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
        self.pages.setTabVisible(2, bool(self.delivered.topLevelItemCount()))
        for index in range(self.delivered.topLevelItemCount()):
            row = self.delivered.topLevelItem(index)
            row.setExpanded(row.data(0, Qt.ItemDataRole.UserRole + 1) in expanded)
            for item in (row, *(row.child(i) for i in range(row.childCount()))):
                if identity and item.data(0, Qt.ItemDataRole.UserRole + 1) == identity:
                    self.delivered.setCurrentItem(item)
        self.delivered.verticalScrollBar().setValue(scroll)

    def inspect_delivered(self, item, column=0):
        if item:
            self.inspect_blocking_phase(item.data(0, Qt.ItemDataRole.UserRole))

    def complete(self, report):
        self.started.clear()
        self.cancelling = False
        self.outcome = report['status']
        self.run_timing = ' · Active time: ' + duration(report.get('seconds'))
        if report.get('attempts'):
            self.run_timing += f' across {len(report["attempts"])} attempt(s)'
        self.flow.set_facts(self.facts)
        self.refresh_summary()
        self.refresh_inspector()

        if self.pages.currentIndex() == 0 and report['status'] == 'passed' and self.pages.isTabVisible(2):
            self.pages.setCurrentIndex(2)

    def unverified(self, reason):
        self.started.clear()
        self.cancelling = False
        self.outcome = 'failed'
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
        lines = [key, 'State: ' + fact.get('status', 'queued')]
        for field in ('reason', 'error', 'summary', 'cleanup_error'):
            if fact.get(field):
                lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
        problems = [case for case in fact.get('tests', []) if case['status'] in {'failed', 'error'}]
        for case in problems[:3]:
            lines += ['', case['name'] + ': ' + case['status'], case['message']]
        if phase:
            lines += ['', f'Gate: {"required" if phase.required else "optional"}',
                      'Dependencies: ' + (', '.join(phase.dependencies) or 'none'),
                      'Timeout: ' + duration(phase.timeout)]
            if getattr(phase, 'waits_for', ()):
                lines.append('Scheduling only: wait for completion of ' + ', '.join(phase.waits_for))
        if fact.get('log'):
            lines.append('Log in results folder: ' + fact['log'])
        for artifact in fact.get('artifacts', []):
            lines += ['Artifact: ' + artifact['path'], 'SHA-256: ' + artifact['sha256']]
        # Caller supplies redacted plan data; report facts are redacted by executor.
        self.detail.setPlainText('\n'.join(lines))

    def refresh_tests(self):
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
                                       ' / '.join(filter(None, [case['suite'], case['classname']])), key])
                item.setData(0, Qt.ItemDataRole.UserRole, case)
                self.tests.addTopLevelItem(item)
                if previous == (key, case):
                    self.tests.setCurrentItem(item)
        self.test_summary.setText(' · '.join(f'{value} {key}' for key, value in counts.items())
                                 if counts else 'No individual case report supplied. Step results remain available.')
        self.result_counts.setText(f'{sum(counts.values())} reported tests\n' + self.test_summary.text())
        for state, (card, label) in self.count_cards.items():
            value = counts.get(state, 0) if counts else '—'
            card.setText(f'<span style="font-size:24pt">{value}</span><br>{label}')
            card.setAccessibleName(f'{value} {label.lower()} tests' if counts else label + ' count not reported yet')
        self.problems_button.setEnabled(bool(counts.get('failed') or counts.get('error')))
        self.timings.clear()
        longest = max((row[0] for row in measured), default=0)
        for seconds, case, key in sorted(measured, key=lambda row: row[0], reverse=True):
            item = QTreeWidgetItem([case['name'], duration(seconds),
                ' / '.join(filter(None, [case['suite'], case['classname']])), key, ''])
            self.timings.addTopLevelItem(item)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(1000 * seconds / longest) if longest else 0)
            bar.setTextVisible(False)
            bar.setAccessibleName(case['name'] + ': ' + duration(seconds))
            bar.setToolTip('Relative to the slowest reported test: ' + duration(longest))
            self.timings.setItemWidget(item, 4, bar)
        if measured:
            from statistics import median
            values = [row[0] for row in measured]
            self.timing_summary.setText(f'{len(values)} timed tests · {missing} without duration\n'
                f'Total reported test time: {duration(sum(values))} · Average: {duration(sum(values)/len(values))} · Median: {duration(median(values))}')
        else:
            self.timing_summary.setText(f'No individual test durations reported. {missing} tests without duration. Step durations are available in Step details.')
        self.tests.setColumnHidden(4, bool(self.selected))
        self.timings.setColumnHidden(3, bool(self.selected))
        self.filter_tests()

    def filter_tests(self, *_):
        query, choice = self.search.text().casefold(), self.filter.currentText()
        for index in range(self.tests.topLevelItemCount()):
            item = self.tests.topLevelItem(index)
            case = item.data(0, Qt.ItemDataRole.UserRole)
            text = ' '.join(str(value) for value in case.values()).casefold()
            visible = (not query or query in text) and (
                choice == 'All tests' or choice == 'Problems' and case['status'] in {'failed', 'error'}
                or choice == 'Passed' and case['status'] == 'passed'
                or choice == 'Skipped' and case['status'] == 'skipped')
            item.setHidden(not visible)

    def show_test(self, item, previous=None):
        if item:
            case = item.data(0, Qt.ItemDataRole.UserRole)
            self.test_detail.setPlainText(f'{case["classname"]}.{case["name"]}\n'
                                          f'{case["status"]} · {duration(case["seconds"])}\n\n{case["message"]}')
