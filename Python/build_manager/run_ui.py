"""Qt-only workflow board shared by live execution and retained results."""
import time
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QSplitter, QVBoxLayout, QWidget)


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.facts, self.started, self.phases = {}, {}, {}, {}
        self.run_timing = ''
        self.outcome = ''
        self.selected = ''
        self.output_lines = deque(maxlen=6000)
        self.phase_log_reader = None
        layout = QVBoxLayout(self)
        self.context = QLabel('Run source and destination will appear here.')
        self.context.setWordWrap(True)
        self.context.setAccessibleName('Source and destination of the displayed run')
        layout.addWidget(self.context)
        self.summary = QLabel('No run yet. Configure your goal and inspect the plan.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
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
        self.tabs = QTabWidget()
        inspector_layout.addWidget(self.tabs, 1)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.flow)
        self.splitter.addWidget(inspector)
        self.splitter.setSizes([490, 590])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        results = QWidget()
        results_layout = QVBoxLayout(results)
        self.result_counts = QLabel('No test reports yet. Counts appear as tests finish.')
        self.result_counts.setWordWrap(True)
        self.result_counts.setAccessibleName('Reported test totals')
        self.next_action = QLabel('Tests and delivery progress will appear here.')
        self.next_action.setWordWrap(True)
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
            text += '\nShared resources: ' + ', '.join(phase.resources)
        for row in getattr(self.plan, 'journey', {}).get('destinations', {}).values():
            if self.selected in row['steps']:
                text += '\nDestination: ' + row['identity']
        self.selection_info.setText(text)
        if state in {'blocked', 'skipped'}:
            self.next_action.setText('This step will not run. ' + reason + '\nSelect its prerequisite cards to inspect the cause.')
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
        self.filter.setCurrentText('Problems')
        self.tabs.setCurrentWidget(self.tests.parentWidget())

    def show_timings(self):
        self.tabs.setCurrentWidget(self.timings.parentWidget())

    def reset(self, plan, previous=()):
        self.plan = plan
        self.selected = ''
        self.output_lines.clear()
        self.flow.reset(plan)
        self.rows, self.facts, self.started = {}, {}, {}
        self.phases = {phase.id: phase for phase in plan.phases}
        source = plan.source.get('fingerprint') or plan.source.get('commit') or plan.source.get('revision', 'see original plan')
        destination = plan.source.get('destination') or plan.settings.get('destination', 'see original plan')
        self.context.setText(f'{plan.project} · {plan.operation} · {plan.backend}\nSource: {source} · Destination: {destination}')
        self.run_timing = ''
        self.outcome = ''
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
        if self.outcome == 'awaiting_review' or counts.get('awaiting_review'):
            action = ('GitHub checks are waiting for approval to start. Review the workflow and exact source before continuing.'
                if any(fact.get('effect')=='dispatch' and fact['status']=='awaiting_review' for fact in self.facts.values())
                else 'Tests and preparation have paused for approval. Use “Review and continue this run…” to inspect the files and destinations.')
        elif self.outcome in {'failed', 'error', 'cancelled', 'interrupted'}:
            action = 'This run did not finish successfully. Open Tests and choose Problems, or inspect Step details for the reason.'
        elif self.outcome == 'unknown':
            action = 'An external action has an unknown outcome. Check its provider status before retrying; the manager will not repeat it automatically.'
        elif self.outcome:
            action = 'Run finished. Check Tests for individual outcomes and Timing for the slowest tests. Start another run from New run.'
        else:
            action = 'Work is in progress. Test totals update as reports arrive. Delivery requires a separate approval.'
        self.next_action.setText(action)
        if self.plan and getattr(self.plan, 'journey', {}):
            from .journeys import outcomes
            self.destinations.setText('\n'.join(label + ': ' + state.replace('_', ' ')
                for label, state in outcomes(self.plan, self.facts.values())))
        else:
            self.destinations.clear()

    def complete(self, report):
        self.started.clear()
        self.outcome = report['status']
        self.run_timing = ' · Active time: ' + duration(report.get('seconds'))
        if report.get('attempts'):
            self.run_timing += f' across {len(report["attempts"])} attempt(s)'
        self.flow.set_facts(self.facts)
        self.refresh_summary()
        self.refresh_inspector()

    def unverified(self, reason):
        self.started.clear()
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
