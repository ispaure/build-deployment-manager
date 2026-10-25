"""Qt-only workflow board shared by live execution and retained results."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)


def duration(seconds):
    if seconds is None:
        return '—'
    return f'{seconds:.2f}s' if seconds < 60 else f'{int(seconds // 60)}m {seconds % 60:.1f}s'


def plan_overview(plan):
    lines = [f'{plan.project} · {plan.operation}', f'Runs on: {plan.backend}',
             f'Workflow effect: {plan.effect}', '', 'Source:']
    if plan.adapter.get('test_suite'):
        lines.insert(3, 'Selected suite: ' + plan.adapter['test_suite'])
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
              '', 'Steps in execution order:']
    for number, phase in enumerate(plan.phases, 1):
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        lines += [f'{number}. {phase.id} · {phase.kind} · {effect}',
                  f'   {"Required" if phase.required else "Optional"}; timeout {duration(phase.timeout)}; '
                  f'depends on: {", ".join(phase.dependencies) or "none"}',
                  '   ' + ('External action: explicit review required.' if effect in {'upload', 'deploy', 'publish'}
                            else 'Preparation / local execution.')]
    return '\n'.join(lines)


class RunView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.facts, self.started, self.phases = {}, {}, {}, {}
        self.run_timing = ''
        self.outcome = ''
        layout = QVBoxLayout(self)
        self.context = QLabel('Run source and destination will appear here.')
        self.context.setWordWrap(True)
        self.context.setAccessibleName('Source and destination of the displayed run')
        layout.addWidget(self.context)
        self.summary = QLabel('No run yet. Configure your goal and inspect the plan.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setAccessibleName('Completed workflow steps')
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        steps = QWidget()
        step_layout = QVBoxLayout(steps)
        self.steps = QTreeWidget()
        self.steps.setHeaderLabels(['Step', 'State / waiting reason', 'Duration', 'Kind', 'Depends on'])
        self.steps.setAccessibleName('Workflow steps and timings')
        self.steps.setColumnWidth(0, 220)
        self.steps.setColumnWidth(1, 250)
        self.steps.setAlternatingRowColors(True)
        self.steps.currentItemChanged.connect(self.show_detail)
        step_layout.addWidget(self.steps, 2)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName('Selected step details and evidence')
        step_layout.addWidget(self.detail, 1)
        self.tabs.addTab(steps, 'Steps')
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
        self.tests.setColumnWidth(0, 280)
        self.tests.setAlternatingRowColors(True)
        self.tests.currentItemChanged.connect(self.show_test)
        test_layout.addWidget(self.tests, 2)
        self.test_detail = QPlainTextEdit()
        self.test_detail.setReadOnly(True)
        self.test_detail.setAccessibleName('Selected test failure or skip details')
        test_layout.addWidget(self.test_detail, 1)
        self.tabs.addTab(tests, 'Tests')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setAccessibleName('Live redacted execution output')
        self.tabs.addTab(self.log, 'Live output')

    def reset(self, plan, previous=()):
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
        elif 'seconds' in event:
            self.started.pop(key, None)
            self.rows[key].setText(2, duration(event['seconds']))
        self.refresh_summary()
        if self.steps.currentItem() == self.rows[key]:
            self.show_detail(self.rows[key])
        if 'tests' in event:
            self.refresh_tests()

    def tick(self):
        for key, started in self.started.items():
            self.rows[key].setText(2, duration(time.monotonic() - started))

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
        text = ' · '.join(f'{value} {key.replace("_", " ")}' for key, value in counts.items()) or 'No steps'
        prefix = ('Workflow: ' + self.outcome.replace('_', ' ') + ' · ') if self.outcome else ''
        self.summary.setText(prefix + text + self.run_timing)

    def complete(self, report):
        self.started.clear()
        self.outcome = report['status']
        self.run_timing = ' · Active time: ' + duration(report.get('seconds'))
        if report.get('attempts'):
            self.run_timing += f' across {len(report["attempts"])} attempt(s)'
        if self.steps.currentItem() is None and self.rows:
            key = next((key for key, fact in self.facts.items()
                        if fact['status'] in {'failed', 'timeout', 'awaiting_review', 'unknown'}), next(iter(self.rows)))
            self.steps.setCurrentItem(self.rows[key])
        self.refresh_summary()

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
        if fact.get('log'):
            lines.append('Log in results folder: ' + fact['log'])
        for artifact in fact.get('artifacts', []):
            lines += ['Artifact: ' + artifact['path'], 'SHA-256: ' + artifact['sha256']]
        # Caller supplies redacted plan data; report facts are redacted by executor.
        self.detail.setPlainText('\n'.join(lines))

    def refresh_tests(self):
        self.tests.clear()
        counts = {}
        for key, fact in self.facts.items():
            for case in fact.get('tests', []):
                status = case['status']
                counts[status] = counts.get(status, 0) + 1
                item = QTreeWidgetItem([case['name'], status, duration(case['seconds']),
                                       ' / '.join(filter(None, [case['suite'], case['classname']])), key])
                item.setData(0, Qt.ItemDataRole.UserRole, case)
                self.tests.addTopLevelItem(item)
        self.test_summary.setText(' · '.join(f'{value} {key}' for key, value in counts.items())
                                 if counts else 'No individual case report supplied. Step results remain available.')
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
