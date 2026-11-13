"""Run summary presentation from explicit plan and RunState facts."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget
from .ui_components import ActionStrip, style_button, HeadingLabel, WrappingLayout


class RunSummaryView(QWidget):
    activity_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        heading = HeadingLabel('Run progress & results')
        layout.addWidget(heading)
        self.summary = QLabel('No run yet. Configure your goal and inspect the plan.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.workflow_action = QLabel('Tests and delivery progress will appear here.')
        self.workflow_action.setWordWrap(True)
        self.workflow_action.setTextFormat(Qt.TextFormat.PlainText)
        self.workflow_action.setAccessibleName('Run outcome and next action')
        self.destinations = QLabel(self)
        self.destinations.setWordWrap(True)
        self.destinations.setAccessibleName('Platform and destination outcomes')
        self.destinations.hide()
        self.progress = QProgressBar()
        self.progress.setAccessibleName('Completed workflow steps')
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.activity = ActionStrip()
        self.activity_buttons = {}
        for state, color in (('running', '#245db5'), ('queued', '#727272'),
                             ('waiting_resource', '#727272'), ('retrying', '#727272'), ('awaiting_review', '#b37c12')):
            button = style_button(QPushButton(self.activity))
            button.setAutoDefault(False)
            button.setStyleSheet(button.styleSheet() + f' QPushButton {{ border-left: 4px solid {color}; }}')
            button.clicked.connect(lambda checked=False, state=state: self.activity_selected.emit(state))
            self.activity_buttons[state] = button
        self.overall_tests = QLabel('No individual case reports available yet.')
        self.overall_tests.setWordWrap(True)

    def present(self, plan, facts, *, outcome, cancelling, run_timing, total_steps):
        phases = {phase.id: phase for phase in plan.phases} if plan else {}
        terminal = {'passed', 'failed', 'error', 'skipped', 'cancelled', 'timeout', 'interrupted', 'unknown'}
        counts = {}
        for fact in facts.values():
            state = fact['status']
            counts[state] = counts.get(state, 0) + 1
        done = sum(value for key, value in counts.items() if key in terminal)
        self.progress.setRange(0, max(1, total_steps))
        self.progress.setValue(done)
        self.progress.setFormat(f'{done} / {total_steps} steps finished')
        from .workflow_presentation import display_states
        visible_counts = {}
        for state, _ in display_states(plan, facts).values() if plan else ():
            visible_counts[state] = visible_counts.get(state, 0) + 1
        text = ' · '.join(f'{value} {key.replace("_", " ")}' for key, value in visible_counts.items()) or 'No steps'
        prefix = ('Workflow: ' + outcome.replace('_', ' ') + ' · ') if outcome else ''
        self.summary.setText(prefix + f'{done} / {total_steps} steps finished · ' + text + run_timing)
        activity_names = {'running': 'Running', 'queued': 'Queued',
            'waiting_resource': 'Waiting for capacity', 'retrying': 'Waiting to reconnect', 'awaiting_review': 'Needs approval'}
        for button in self.activity_buttons.values():
            self.activity.grid.removeWidget(button)
        active = []
        for state, button in self.activity_buttons.items():
            count = visible_counts.get(state, 0)
            button.setText(activity_names[state] + ' · ' + str(count))
            button.setVisible(bool(count) and not outcome)
            button.setEnabled(not cancelling)
            if count and not outcome:
                active.append(button)
        self.activity.buttons, self.activity.columns = active, 0
        self.activity.reflow()
        self.activity.setVisible(not outcome and any(visible_counts.get(state) for state in activity_names))
        if cancelling:
            self.summary.setText('Stopping… · ' + text + run_timing)
        self.progress.setAccessibleDescription(self.summary.text())
        cases = [case for fact in facts.values() for case in fact.get('tests', ())]
        problems = sum(case['status'] in {'failed', 'error'} for case in cases)
        self.overall_tests.setText(f'{len(cases)} reported test cases · {problems} problems' if cases
            else 'No individual case reports available yet. Step outcomes remain available.')
        interim = sum(len(fact.get('live_tests', ())) for fact in facts.values())
        if interim:
            self.overall_tests.setText(f'{interim} interim test results · suites still running' +
                (f' · {len(cases)} final results' if cases else ''))
        self.overall_tests.setVisible(bool(cases or interim))
        if outcome == 'unknown' or counts.get('unknown'):
            action = 'An external action has an unknown outcome. Check its provider status before retrying; the manager will not repeat it automatically.'
        elif outcome == 'awaiting_review' or counts.get('awaiting_review'):
            action = ('GitHub checks are waiting for approval to start. Review the workflow and exact source before continuing.'
                if any(fact['status']=='awaiting_review' and (fact.get('effect') or
                    (phases[key].effect if phases[key].effect != 'inherit' else plan.effect)) == 'dispatch'
                    for key, fact in facts.items() if key in phases)
                else 'Eligible actions need approval. Use the review action below to inspect prepared files, exact source and destinations. Independent blocked branches remain separate.')
        elif outcome in {'failed', 'error', 'cancelled', 'interrupted'}:
            action = 'This run did not finish successfully. Use View problems, or open a workflow card and select a step to inspect the reason.'
        elif outcome == 'passed':
            destinations = getattr(plan, 'journey', {}).get('destinations', {}) if plan else {}
            delivered = sum(all(facts.get(key, {}).get('status') == 'passed' for key in row['steps'])
                for row in destinations.values())
            files = len({(a['path'], a.get('sha256', '')) for fact in facts.values()
                         for a in fact.get('artifacts', ())})
            action = f'{delivered} of {len(destinations)} destinations delivered' if destinations else 'Completed'
            if files:
                action += f' · {files} retained file' + ('s' if files != 1 else '')
        elif outcome:
            action = 'Run finished. Check the evidence for individual step outcomes.'
        else:
            action = 'Work is in progress. Test totals update as reports arrive. Delivery requires a separate approval.'
        self.workflow_action.setText(action)
        if plan and getattr(plan, 'journey', {}):
            from .journeys import outcomes
            self.destinations.setText('\n'.join(label + ': ' + state.replace('_', ' ')
                for label, state in outcomes(plan, facts.values())))
        else:
            self.destinations.clear()


class RunOutcomeView(QWidget):
    failed_case_requested = Signal()
    logs_requested = Signal()
    blocker_requested = Signal()
    files_requested = Signal()
    diagnostics_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.heading = HeadingLabel(section=True)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.message = QLabel()
        self.problems = QLabel()
        self.deliveries = QLabel()
        self.guidance = QLabel()
        for label in (self.heading, self.message, self.guidance, self.problems, self.deliveries):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            layout.addWidget(label)
        actions = WrappingLayout()
        self.failed_case = self.add_action(actions, 'View failing test', self.failed_case_requested)
        self.copy = self.add_action(actions, 'Copy diagnostics…', self.diagnostics_requested)
        self.logs = self.add_action(actions, 'View logs', self.logs_requested)
        self.blocker = self.add_action(actions, 'View blocking step', self.blocker_requested)
        self.files = self.add_action(actions, 'View deliveries', self.files_requested)
        layout.addLayout(actions)

    @staticmethod
    def add_action(layout, text, signal):
        button = style_button(QPushButton(text))
        button.clicked.connect(signal.emit)
        layout.addWidget(button)
        button.hide()
        return button

    def present(self, *, heading, message, guidance, problems, deliveries, case=False, logs=False,
                blocker=False, files=False, diagnostics=False):
        for label, text in ((self.heading, heading), (self.message, message), (self.guidance, guidance),
                            (self.problems, problems), (self.deliveries, deliveries)):
            if text != label.text():
                label.setText(text)
            label.setVisible(bool(text))
        for button, visible in ((self.failed_case, case), (self.logs, logs), (self.blocker, blocker),
                                (self.files, files), (self.copy, diagnostics)):
            button.setVisible(visible)
