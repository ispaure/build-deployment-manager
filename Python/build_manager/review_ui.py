"""One review map and a persistent, synchronized task/evidence inspector."""
import shlex
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHeaderView, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyle, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from .grouped_workflow_ui import GroupedFlowView
from .plan_summary import captured_choices, phase_title, summary_rows
from .workflow_ui import WorkflowFlow, blocking_prerequisite, display_states, state_label, step_time


class Disclosure(QWidget):
    def __init__(self, label, content):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(label)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.content = content
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        self.toggle.toggled.connect(self.expand)
        self.expand(False)

    def expand(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


def text_view(name):
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setAccessibleName(name)
    view.setMinimumHeight(140)
    return view


class ReviewPlanView(QWidget):
    phase_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan, self.phases, self.facts, self.rows = None, {}, {}, {}
        self.selected, self.detail_selection = '', None
        self.log_reader = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.captured = QLabel()
        self.captured.setWordWrap(True)
        self.captured.setTextFormat(Qt.TextFormat.PlainText)
        self.captured.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_details = Disclosure('Captured source and run choices', self.captured)
        layout.addWidget(self.source_details)
        self.problems = QPushButton('Inspect failure')
        self.problems.setAccessibleName('Inspect failed step and crash evidence')
        self.problems.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical))
        self.problems.clicked.connect(self.show_problems)
        self.problems.hide()
        layout.addWidget(self.problems)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.flow = GroupedFlowView(graph_mode=True)
        self.graph = WorkflowFlow(graph_only=True)
        self.flow.attach_inspector(self.graph)
        self.flow.group_selected.connect(self.select_group)
        self.graph.phase_selected.connect(self.select_step)
        self.splitter.addWidget(self.flow)
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inspector_scroll.setMinimumWidth(300)
        self.inspector = QWidget()
        self.inspector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.inspector_scroll.setWidget(self.inspector)
        side = QVBoxLayout(self.inspector)
        side.setContentsMargins(8, 0, 4, 0)
        self.task_heading = QLabel('All execution steps')
        self.task_heading.setWordWrap(True)
        self.task_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.task_heading.setStyleSheet('font-weight: 600;')
        side.addWidget(self.task_heading)
        self.tasks = QTreeWidget()
        self.tasks.setHeaderLabels(['Task', 'State', 'Time'])
        self.tasks.setAccessibleName('Tasks in the selected workflow card and its prerequisites')
        self.tasks.setRootIsDecorated(False)
        self.tasks.setWordWrap(True)
        self.tasks.setMinimumHeight(130)
        self.tasks.setMaximumHeight(200)
        self.tasks.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.tasks.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks.currentItemChanged.connect(self.task_changed)
        side.addWidget(self.tasks)
        self.selection_heading = QLabel('Whole workflow')
        self.selection_heading.setWordWrap(True)
        self.selection_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_heading.setStyleSheet('font-weight: 600;')
        side.addWidget(self.selection_heading)
        self.blocking_key = ''
        self.blocker = QPushButton('View blocking step')
        self.blocker.clicked.connect(lambda: self.inspect_phase(self.blocking_key))
        self.blocker.hide()
        side.addWidget(self.blocker)
        self.context_info = QLabel()
        self.context_info.setWordWrap(True)
        self.context_info.setTextFormat(Qt.TextFormat.PlainText)
        self.context_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        side.addWidget(self.context_info)
        self.error_panel = QGroupBox('Error details')
        self.error_panel.setAccessibleName('Selected step error, traceback and captured output')
        error_layout = QVBoxLayout(self.error_panel)
        self.error_summary = QLabel()
        self.error_summary.setWordWrap(True)
        self.error_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.error_summary.setStyleSheet('font-weight: 600;')
        error_layout.addWidget(self.error_summary)
        self.details = text_view('Full error traceback, test failures and captured output')
        error_layout.addWidget(self.details)
        side.addWidget(self.error_panel)
        self.error_panel.hide()
        self.fact_panel = QWidget()
        self.fact_form = QFormLayout(self.fact_panel)
        self.fact_form.setContentsMargins(0, 0, 0, 0)
        self.fact_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fact_values = {}
        for label in ('Purpose', 'Runs on', 'Elapsed', 'Result', 'Outputs', 'Delivery', 'Notes'):
            value = QLabel()
            value.setWordWrap(True)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.fact_values[label] = value
            self.fact_form.addRow(label, value)
        side.addWidget(self.fact_panel)
        self.prerequisites = QWidget()
        self.prerequisite_layout = QVBoxLayout(self.prerequisites)
        self.prerequisite_layout.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.prerequisites)
        self.command = text_view('Exact selected step command and execution settings')
        self.command_section = Disclosure('Command && execution details', self.command)
        side.addWidget(self.command_section)
        technical = QWidget()
        technical_layout = QVBoxLayout(technical)
        technical_layout.setContentsMargins(0, 0, 0, 0)
        self.overview = text_view('Readable complete plan')
        self.plan_data = text_view('Complete redacted plan data')
        self.board = QTreeWidget()
        self.board.setHeaderLabels(['Planned work', 'Starts after', 'What happens'])
        self.board.setMinimumHeight(140)
        self.board.setAccessibleName('Every declared dependency')
        for label, widget in [('Readable plan', self.overview), ('Dependency table', self.board), ('Complete plan data', self.plan_data)]:
            technical_layout.addWidget(Disclosure(label, widget))
        self.technical_section = Disclosure('Full plan && commands', technical)
        side.addWidget(self.technical_section)
        side.addStretch()
        self.splitter.addWidget(self.inspector_scroll)
        self.splitter.setSizes([750, 330])
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)

    def reset(self, plan, fields=(), *, capability=None, proposal=None, summary='', inputs=''):
        self.plan, self.fields, self.summary = plan, fields, summary
        self.phases = {phase.id: phase for phase in plan.phases}
        self.selected, self.facts, self.detail_selection = '', {}, None
        self.captured.setText('\n\n'.join(name + ': ' + value for name, value in captured_choices(plan)) +
                              ('\n\nCaptured notes and recipients:\n' + inputs if inputs else ''))
        source = plan.source.get('commit') or plan.source.get('fingerprint') or plan.source.get('revision', 'Captured source')
        self.source_details.toggle.setText('Source: ' + str(source)[:16] + ' · ' + str(len(plan.phases)) + ' execution steps · captured choices')
        for disclosure in (self.source_details, self.command_section, self.technical_section):
            disclosure.toggle.setChecked(False)
        self.graph.reset(plan, preview=True)
        self.flow.reset(plan, fields, preview=True, capability=capability, proposal=proposal)
        self.problems.hide()
        self.select_group('')

    def scope_keys(self):
        if not self.flow.selected or self.flow.pages.currentIndex() == 0:
            return tuple(self.phases)
        visible = set(self.flow.group_keys(self.flow.selected))
        pending = list(visible)
        while pending:
            phase = self.phases[pending.pop()]
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())):
                if parent not in visible:
                    visible.add(parent)
                    pending.append(parent)
        return tuple(key for key in self.phases if key in visible)

    def select_group(self, key):
        if not key:
            self.flow.selected = ''
        self.selected = ''
        keys = self.scope_keys()
        if key:
            self.graph.set_scope(keys)
            self.graph.setVisible(bool(keys))
            self.task_heading.setText(self.flow.heading.text() +
                (f'\n{len(set(keys) - set(self.flow.group_keys(key)))} prerequisite steps from other cards'
                 if set(keys) - set(self.flow.group_keys(key)) else ''))
        else:
            self.task_heading.setText('All execution steps · ' + str(len(keys)))
        self.tasks.blockSignals(True)
        self.tasks.clear()
        self.rows = {}
        members = set(self.flow.group_keys(key)) if key else set(keys)
        self.task_names = self.short_names(keys)
        for phase_id in keys:
            phase = self.phases[phase_id]
            row = QTreeWidgetItem([self.task_names[phase_id], '', ''])
            row.setData(0, Qt.ItemDataRole.UserRole, phase_id)
            row.setToolTip(0, phase_title(phase) + '\nStep identity: ' + phase_id + ('\nPrerequisite from another card' if phase_id not in members else ''))
            self.tasks.addTopLevelItem(row)
            self.rows[phase_id] = row
        self.tasks.blockSignals(False)
        self.size_task_list(False)
        self.refresh_rows()
        chosen = next((phase_id for phase_id in keys if self.is_problem(phase_id)), '')
        if key and not chosen:
            chosen = next((phase_id for phase_id in keys if phase_id in members), '')
        self.graph.select(chosen) if key else self.select_step('')

    def size_task_list(self, error_visible):
        row_height = self.tasks.fontMetrics().height() + 6
        limit = 120 if error_visible else 190
        self.tasks.setFixedHeight(min(limit, max(85, self.tasks.header().height() + row_height * len(self.rows) + 4)))

    def task_changed(self, row, previous=None):
        if row is not None:
            self.inspect_phase(row.data(0, Qt.ItemDataRole.UserRole))

    def inspect_phase(self, key):
        if key not in self.phases:
            return
        if self.flow.pages.currentIndex() == 0 or key not in self.graph.canvas.cards:
            group = next((group for group in self.flow.grouped.members if key in self.flow.group_keys(group)), '__unassigned__')
            self.flow.open_group(group)
        self.graph.select(key)

    def select_step(self, key):
        changed = self.selected != key
        self.selected = key
        self.tasks.blockSignals(True)
        row = self.rows.get(key)
        self.tasks.setCurrentItem(row)
        if row:
            self.tasks.scrollToItem(row)
        self.tasks.blockSignals(False)
        self.render_details()
        if changed:
            self.inspector_scroll.verticalScrollBar().setValue(0)
        self.phase_selected.emit(key)

    def is_problem(self, key):
        fact = self.facts.get(key, {})
        return fact.get('status') in {'failed', 'error', 'timeout', 'unknown', 'interrupted', 'cancelled'} or any(
            case.get('status') in {'failed', 'error'} for case in fact.get('tests', ()))

    def refresh_rows(self):
        states = display_states(self.plan, self.facts, preview=not bool(self.facts))
        for key, row in self.rows.items():
            state, reason = states[key]
            row.setText(1, {'awaiting_review': 'Approval', 'waiting_resource': 'Waiting'}.get(state, state.replace('_', ' ').capitalize()))
            elapsed = step_time(self.facts.get(key, {}), state) or 'Not recorded'
            row.setText(2, '—' if elapsed in {'Not started', 'Not recorded'} else elapsed)
            row.setToolTip(2, elapsed)
            row.setToolTip(1, reason)
            row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
                if self.is_problem(key) else self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))

    def set_facts(self, facts):
        if self.plan is None:
            return
        self.facts = {key: fact for key, fact in facts.items() if key in self.phases}
        self.graph.preview = not bool(self.facts)
        self.graph.update_guidance()
        self.graph.set_facts(self.facts)
        self.flow.set_facts(self.facts)
        self.refresh_rows()
        problems = sum(self.is_problem(key) for key in self.phases)
        self.problems.setText(f'{problems} step' + ('s' if problems != 1 else '') + ' with errors · View error details')
        self.problems.setVisible(bool(problems))
        self.render_details()

    def show_problems(self):
        key = next((key for key in self.phases if self.is_problem(key)), '')
        if key:
            self.inspect_phase(key)
            self.details.setFocus()
            self.inspector_scroll.ensureWidgetVisible(self.error_summary)

    def short_names(self, keys):
        parts = {key: phase_title(self.phases[key]).split(' · ') for key in keys}
        names = {}
        for key, segments in parts.items():
            for count in range(1, len(segments) + 1):
                name = ' · '.join(segments[-count:])
                if not any(name == ' · '.join(other[-count:]) for other_key, other in parts.items() if other_key != key):
                    break
            names[key] = name[:1].upper() + name[1:]
        return names

    def set_fact(self, label, text):
        self.fact_values[label].setText(text)
        self.fact_form.setRowVisible(self.fact_values[label], bool(text))

    def execution_location(self, key):
        journey = getattr(self.plan, 'journey', {})
        targets = {target for target, steps in journey.get('platforms', {}).items() if key in steps}
        for node in self.flow.grouped.phases:
            if key in self.flow.group_keys(node.id):
                targets.update(getattr(node, 'platforms', ()))
                if node.id.startswith('platform.'):
                    targets.add(node.id.removeprefix('platform.'))
        locations = [journey.get('executions', {}).get(target, {}).get('backend', '') for target in sorted(targets)]
        return ', '.join(dict.fromkeys(filter(None, locations))) or self.plan.backend

    def render_details(self):
        key = self.selected
        while self.prerequisite_layout.count():
            widget = self.prerequisite_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        for label in self.fact_values:
            self.set_fact(label, '')
        self.command_section.setVisible(bool(key))
        self.fact_panel.setVisible(bool(key))
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, key) if self.facts and key else ''
        self.blocker.setVisible(bool(self.blocking_key))
        problem = bool(key and self.is_problem(key))
        self.error_panel.setVisible(problem)
        self.size_task_list(problem)
        self.error_summary.clear()
        self.context_info.clear()
        self.context_info.hide()
        self.selection_heading.setVisible(bool(key))
        if not key:
            if self.flow.selected == 'source':
                self.selection_heading.setText('Captured source')
                self.selection_heading.show()
                self.context_info.setText(captured_choices(self.plan)[0][1] +
                    '\n\nNo executable source subtasks were declared.' if not self.flow.group_keys('source')
                    else captured_choices(self.plan)[0][1])
                self.context_info.show()
            self.set_detail_text('', key)
            return
        phase, fact = self.phases[key], self.facts.get(key, {})
        state, reason = display_states(self.plan, self.facts, preview=not bool(self.facts))[key]
        self.selection_heading.setText(self.task_names.get(key, phase_title(phase)))
        self.selection_heading.setToolTip(phase_title(phase) + '\n' + key)
        if problem:
            lines = []
            for field in ('error', 'reason', 'summary', 'cleanup_error'):
                if fact.get(field):
                    lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
            if fact.get('exit_code') is not None:
                lines.append('Exit code: ' + str(fact['exit_code']))
            for case in fact.get('tests', ()):
                if case.get('status') in {'failed', 'error'}:
                    lines.append(case['name'] + ' · ' + case['status'] + '\n' + str(case.get('message', '')))
            if reason and reason not in (fact.get('error'), fact.get('reason')):
                lines.append(reason)
            self.error_summary.setText(str(fact.get('error') or fact.get('reason') or state_label(state)).splitlines()[0])
            if self.log_reader and fact.get('log'):
                try:
                    lines += ['Captured step output:', self.log_reader(key)]
                except (OSError, ValueError, TypeError) as error:
                    lines.append('Could not read captured step output: ' + str(error))
            self.set_detail_text('\n\n'.join(lines) or 'No error message was captured. Inspect the step command and retained output.', key)
        else:
            self.set_detail_text('', key)
        description = getattr(phase, 'description', '')
        self.set_fact('Purpose', description)
        self.set_fact('Runs on', self.execution_location(key))
        elapsed = step_time(fact, state)
        self.set_fact('Elapsed', elapsed if elapsed not in {'', 'Not started'} else '')
        if self.blocking_key:
            self.set_fact('Result', 'Blocked by ' + self.task_names.get(self.blocking_key, phase_title(self.phases[self.blocking_key])))
        elif state == 'waiting_resource':
            self.set_fact('Result', reason)
        self.set_fact('Outputs', '\n'.join(path.replace('\\', '/').rsplit('/', 1)[-1] for path in phase.artifacts))
        self.fact_values['Outputs'].setToolTip('\n'.join(phase.artifacts))
        effect = phase.effect if phase.effect != 'inherit' else self.plan.effect
        destinations = [destination['identity'] for destination in getattr(self.plan, 'journey', {}).get('destinations', {}).values()
                        if key in destination['steps']]
        delivery = '\n'.join(destinations)
        if effect in {'upload', 'deploy', 'publish', 'dispatch'}:
            delivery += ('\n' if delivery else '') + 'Separate approval required'
        self.set_fact('Delivery', delivery)
        _, later, shared = summary_rows(self.plan, self.fields)
        notes = []
        for row in later:
            if key in row['keys']:
                for line in row['detail'].splitlines():
                    if not line.startswith(('Upload', 'Deliver', 'Publish', 'Launch', 'Destination:', 'Requires platforms:', 'Waits for:')):
                        notes.append(line)
        self.set_fact('Notes', '\n'.join([*notes, *shared]))
        parents = tuple(dict.fromkeys((*phase.dependencies, *getattr(phase, 'waits_for', ()))))
        if parents:
            heading = QLabel('Prerequisites')
            heading.setStyleSheet('font-weight: 600;')
            self.prerequisite_layout.addWidget(heading)
        from .ui_components import SelectionSummary
        for parent in parents:
            button = SelectionSummary()
            label = self.task_names.get(parent, phase_title(self.phases[parent]))
            if parent in getattr(phase, 'waits_for', ()):
                label += ' · wait for completion'
            button.set_summary(label)
            button.setToolTip(phase_title(self.phases[parent]) + '\n' + parent)
            button.clicked.connect(lambda checked=False, parent=parent: self.inspect_phase(parent))
            self.prerequisite_layout.addWidget(button)
        from .resources import resource_details
        technical = ['Step identity: ' + key, shlex.join(phase.argv), 'Working directory: ' + phase.cwd,
                     'Required for success: ' + ('Yes' if phase.required else 'No'), 'Timeout: ' + str(phase.timeout) + ' seconds',
                     'Success prerequisites: ' + (', '.join(phase.dependencies) or 'None'),
                     'Waits for completion: ' + (', '.join(getattr(phase, 'waits_for', ())) or 'None')]
        if phase.always:
            technical.append('Runs after prerequisites finish, including after failure.')
        technical.extend(resource_details(self.plan, key))
        if phase.environment:
            technical.append('Environment references:\n' + '\n'.join(f'{name}={value}' for name, value in phase.environment.items()))
        self.command.setPlainText('\n\n'.join(technical))

    def set_detail_text(self, text, selection):
        if self.details.toPlainText() == text and self.detail_selection == selection:
            return
        same = self.detail_selection == selection
        cursor = self.details.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        scroll = self.details.verticalScrollBar().value()
        self.details.setPlainText(text)
        if same:
            cursor = self.details.textCursor()
            last = self.details.document().characterCount() - 1
            cursor.setPosition(min(anchor, last))
            cursor.setPosition(min(position, last), QTextCursor.MoveMode.KeepAnchor)
            self.details.setTextCursor(cursor)
            self.details.verticalScrollBar().setValue(scroll)
        else:
            self.details.verticalScrollBar().setValue(0)
        self.detail_selection = selection
