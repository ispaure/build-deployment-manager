"""Familiar journey cards with an in-place desktop subtask browser."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget, QSizePolicy)
from .grouped_workflow import group_workflow
from .plan_summary import captured_choices, phase_title, summary_rows
from .workflow_ui import FlowCanvas, FitMapView, WorkflowFlow, display_states, effect_label, blocking_prerequisite, orientation_picker
from .ui_components import style_button, ViewportStack


class GroupedFlowView(QWidget):
    phase_selected = Signal(str)
    blocker_selected = Signal(str)
    problems_selected = Signal(str)
    group_selected = Signal(str)

    def __init__(self, parent=None, *, graph_mode=False, inspect_single_cards=False):
        super().__init__(parent)
        self.plan, self.selected, self.facts = None, '', {}
        self.graph_mode = graph_mode
        self.inspect_single_cards = inspect_single_cards
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = ViewportStack()
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        overview = QWidget()
        body = QVBoxLayout(overview)
        self.overview_layout = body
        body.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.additional = QPushButton()
        self.additional.clicked.connect(lambda: self.open_group('__unassigned__'))
        toolbar.addWidget(self.additional)
        toolbar.addStretch()
        self.canvas = FlowCanvas()
        self.canvas.selected.connect(self.open_group)
        self.map = FitMapView(self.canvas)
        self.orientation = orientation_picker(self.map)
        toolbar.addWidget(self.orientation)
        self.map.setMinimumHeight(180)
        for title, callback in [('Fit', self.fit), ('+', lambda: self.map.zoom(1.2)), ('−', lambda: self.map.zoom(1 / 1.2))]:
            button = QPushButton(title)
            button.setAccessibleName({'Fit': 'Fit entire workflow', '+': 'Zoom in', '−': 'Zoom out'}[title])
            button.setToolTip(button.accessibleName())
            if title == '+':
                self.zoom_in = button
            elif title == '−':
                self.zoom_out = button
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        self.map.scale_changed.connect(lambda scale: self.zoom_out.setEnabled(scale > self.map.minimum_scale))
        self.map.scale_changed.connect(lambda scale: self.zoom_in.setEnabled(scale < self.map.maximum_scale))
        body.addLayout(toolbar)
        body.addWidget(self.map, 1)
        self.pages.addWidget(overview)
        inside = QWidget()
        inner = QVBoxLayout(inside)
        inner.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        self.back = QPushButton('← All workflow cards')
        self.back.clicked.connect(self.close_group)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        navigation.addWidget(self.back)
        navigation.addWidget(self.heading, 1)
        inner.addLayout(navigation)
        self.splitter = QSplitter()
        inner.addWidget(self.splitter, 1)
        if not graph_mode:
            self.step_flow = WorkflowFlow(graph_only=True)
            self.step_flow.phase_selected.connect(self.show_task)
            self.details = QPlainTextEdit()
            self.details.setReadOnly(True)
            self.details.setAccessibleName('Selected card or subtask details')
            self.splitter.addWidget(self.step_flow)
            self.splitter.addWidget(self.details)
            self.splitter.setSizes([750, 250])
            self.splitter.setStretchFactor(0, 3)
            self.splitter.setStretchFactor(1, 1)
            self.splitter.setChildrenCollapsible(False)
            self.inspect = QPushButton('Inspect selected step in full workflow…')
            self.inspect.clicked.connect(self.inspect_task)
            self.problems = QPushButton('View selected step problems')
            self.problems.clicked.connect(lambda: self.problems_selected.emit(
                self.step_flow.selected) if self.step_flow.selected else None)
            self.problems.hide()
            self.blocker = style_button(QPushButton('View blocking step'))
            self.blocker.clicked.connect(lambda: self.blocker_selected.emit(self.blocking_key) if self.blocking_key else None)
            self.blocking_key = ''
            self.blocker.hide()
            actions = QHBoxLayout()
            actions.addWidget(self.blocker)
            actions.addWidget(self.problems)
            actions.addStretch()
            actions.addWidget(self.inspect)
            inner.addLayout(actions)
        self.pages.addWidget(inside)
        layout.addWidget(self.pages, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fit)
        self.rows = {}
        self.graph = None

    def attach_inspector(self, graph, inspector=None):
        """Live runs have one graph and one inspector, shared by every card."""
        self.graph = graph
        self.inspector = inspector
        self.splitter.addWidget(graph)
        if inspector is not None:
            self.splitter.addWidget(inspector)
        self.splitter.setSizes([600, 500])
        self.splitter.setChildrenCollapsible(False)
        graph.show()
        if inspector is not None:
            inspector.show()

    def reset(self, plan, fields=(), *, preview=True, capability=None, proposal=None):
        self.plan, self.fields, self.preview = plan, fields, preview
        self.grouped = group_workflow(plan, capability, proposal)
        self.phases = {phase.id: phase for phase in plan.phases}
        self.additional.setText(f'Other resolved subtasks ({len(self.grouped.unassigned)})…')
        self.additional.setVisible(bool(self.grouped.unassigned))
        self.selected, self.facts = '', {}
        self.rows = {}
        if not self.graph_mode:
            self.step_flow.reset(plan, preview=preview)
            self.details.clear()
        self.detail_selection = None
        self.pages.setCurrentIndex(0)
        self.canvas.reset(self.grouped, reserve_activity=not preview)
        self.map.reset_view()
        self.set_facts({})
        self.timer.start(0)

    def fit(self):
        self.map.fit_mode = True
        self.map.fit_map(force=True)

    def open_group(self, key):
        if not key:
            self.selected = ''
            self.set_facts(self.facts)
            self.group_selected.emit('')
            return
        self.selected = key
        node = next((node for node in self.grouped.phases if node.id == key), None)
        keys = self.group_keys(key)
        self.heading.setText((node.label if node else 'Other execution steps') +
            f' · {len(keys)} execution step' + ('s' if len(keys) != 1 else ''))
        owned = self.grouped.members.get(key, ()) if key != '__unassigned__' else keys
        if len(owned) <= 1:
            # Selecting a leaf scopes its inspector; it is not another page.
            self.pages.setCurrentIndex(0)
            if self.graph is not None:
                self.graph.set_scope(keys)
                self.graph.setVisible(False)
            inspector = getattr(self, 'inspector', None)
            if inspector is not None:
                self.overview_layout.addWidget(inspector, 2)
                inspector.show()
            self.set_facts(self.facts)
            self.group_selected.emit(key)
            if self.graph is None and keys:
                self.phase_selected.emit(keys[0])
            return
        inspector = getattr(self, 'inspector', None)
        if inspector is not None:
            self.splitter.addWidget(inspector)
            inspector.show()
        if self.graph is not None:
            self.heading.setText((node.label if node else 'Other execution steps') +
                f' · {len(keys)} execution step' + ('s' if len(keys) != 1 else ''))
            owned = self.grouped.members.get(key, ()) if key != '__unassigned__' else keys
            expanded = len(owned) > 1 if self.inspect_single_cards else True
            if expanded:
                self.graph.set_scope(keys)
            if self.inspect_single_cards:
                self.graph.setVisible(expanded and bool(keys))
            self.pages.setCurrentIndex(1 if expanded else 0)
            if not expanded:
                self.set_facts(self.facts)
            self.group_selected.emit(key)
            return
        self.heading.setText((node.label if node else 'Other resolved subtasks') + ' · ' + str(len(keys)) + ' execution step' + ('s' if len(keys) != 1 else ''))
        # Keep upstream dependencies visible even when another overview card owns
        # them, so a single-step delivery card still explains its actual gates.
        visible = set(keys)
        pending = list(keys)
        while pending:
            phase = self.phases[pending.pop()]
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())):
                if parent not in visible:
                    visible.add(parent)
                    pending.append(parent)
        self.step_flow.set_scope(visible)
        external_count = len(visible) - len(keys)
        if external_count:
            self.heading.setText(self.heading.text() + f' · {external_count} prerequisite step' +
                ('s' if external_count != 1 else '') + ' from other cards')
        self.step_flow.setVisible(bool(keys))
        self.pages.setCurrentIndex(1)
        self.set_facts(self.facts)
        self.step_flow.select(keys[0] if keys else '')
        if keys:
            self.step_flow.canvas.cards[keys[0]][0].setFocus()
        else:
            self.details.setFocus()

    def group_keys(self, key):
        if key == '__unassigned__':
            return self.grouped.unassigned
        return tuple(dict.fromkeys((*self.grouped.members[key], *self.grouped.references.get(key, ()))))

    def close_group(self):
        key = self.selected
        self.selected = ''
        inspector = getattr(self, 'inspector', None)
        if inspector is not None:
            self.splitter.addWidget(inspector)
        self.pages.setCurrentIndex(0)
        if self.graph is not None:
            self.group_selected.emit('')
        self.set_facts(self.facts)
        self.timer.start(0)
        if key in self.canvas.cards:
            self.canvas.cards[key][0].setFocus()

    def has_group_scope(self):
        return bool(self.selected)

    def group_context(self):
        lines = []
        if self.selected == 'source':
            lines.extend(name + ': ' + value for name, value in captured_choices(self.plan))
            if not self.grouped.members[self.selected]:
                lines.append('Source was captured during plan preparation. No executable source subtasks were declared.')
        _, later, shared = summary_rows(self.plan, self.fields)
        keys = set(self.group_keys(self.selected)) if self.selected else set()
        if self.selected in self.grouped.notes:
            lines.append(self.grouped.notes[self.selected])
        if self.selected and not keys and self.selected != 'source':
            lines.append('This is a chosen workflow card. The project did not declare separately mapped subtasks for it. Use Other resolved subtasks or the full workflow to inspect remaining work.')
        if self.selected and self.grouped.references.get(self.selected):
            lines.append('Shared task references are also used by other workflow cards.')
        node = next((node for node in self.grouped.phases if node.id == self.selected), None)
        if node and self.selected != 'source':
            lines.insert(0, node.label + '\n' + node.description)
        waits = list(dict.fromkeys(parent for key in keys for parent in getattr(self.phases[key], 'waits_for', ()) if parent not in keys))
        if waits:
            lines.append('Scheduling: waits for ' + ', '.join(phase_title(self.phases[key]) for key in waits) + ' to finish; success is not required.')
        if keys:
            lines.append('Arrows show prerequisites. Independent steps can overlap.')
            external = list(dict.fromkeys(parent for key in self.group_keys(self.selected)
                for parent in self.phases[key].dependencies if parent not in keys))
            if external:
                lines.append('Prerequisites outside this card: ' + ', '.join(phase_title(self.phases[key]) for key in external) +
                    ('. These steps are included in the map.' if not self.graph_mode else '. Use the prerequisite control to inspect them.'))
        for row in later:
            if keys.intersection(row['keys']):
                lines.append(row['detail'])
        if shared:
            lines += ['Shared captured values:', *shared]
        return '\n\n'.join(lines)

    def show_task(self, key):
        self.inspect.setEnabled(bool(key))
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, key) if key and not self.preview else ''
        self.blocker.setVisible(bool(self.blocking_key))
        fact = self.facts.get(key, {})
        problems = [case for case in fact.get('tests', ()) if case['status'] in {'failed', 'error'}]
        self.problems.setVisible(bool(key) and not self.preview and (
            fact.get('status') in {'failed', 'error', 'timeout', 'unknown', 'interrupted', 'cancelled'} or bool(problems)))
        lines = []
        if key:
            phase = self.phases[key]
            state, reason = display_states(self.plan, self.facts, self.preview)[key]
            lines += [phase_title(phase), 'State: ' + state.replace('_', ' ')]
            if reason:
                lines.append(reason)
            for field in ('error', 'summary', 'cleanup_error'):
                if fact.get(field) and str(fact[field]) != reason:
                    lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
            for case in problems[:3]:
                lines.append(case['name'] + ': ' + case['status'] + '\n' + str(case.get('message', '')))
            if len(problems) > 3:
                lines.append(f'{len(problems)} test problems. Use View selected step problems to inspect all of them.')
            lines += [effect_label(phase, self.plan),
                      'Prerequisites: ' + (', '.join(phase_title(self.phases[parent]) for parent in phase.dependencies) or 'None')]
            if getattr(phase, 'waits_for', ()):
                lines.append('Waits for completion: ' + ', '.join(phase.waits_for))
            from .resources import resource_details
            lines.extend(resource_details(self.plan, key))
            lines += ['Required: ' + ('Yes' if phase.required else 'No'), 'Timeout: ' + str(phase.timeout) + ' seconds']
            if phase.artifacts:
                lines += ['Declared outputs:', *phase.artifacts]
        lines += [self.group_context(), 'Opening cards and subtasks starts no commands.']
        text = '\n\n'.join(filter(None, lines))
        selection = (self.selected, key)
        if selection != self.detail_selection or text != self.details.toPlainText():
            same_selection = selection == self.detail_selection
            cursor = self.details.textCursor()
            position, anchor = cursor.position(), cursor.anchor()
            vertical = self.details.verticalScrollBar().value()
            horizontal = self.details.horizontalScrollBar().value()
            self.details.setPlainText(text)
            if same_selection:
                cursor = self.details.textCursor()
                last = self.details.document().characterCount() - 1
                cursor.setPosition(min(anchor, last))
                cursor.setPosition(min(position, last), QTextCursor.MoveMode.KeepAnchor)
                self.details.setTextCursor(cursor)
                self.details.verticalScrollBar().setValue(vertical)
                self.details.horizontalScrollBar().setValue(horizontal)
        self.detail_selection = selection

    def inspect_task(self):
        if self.step_flow.selected:
            self.phase_selected.emit(self.step_flow.selected)

    def set_facts(self, facts):
        self.facts = facts
        if self.plan is None:
            return
        states = display_states(self.plan, facts, self.preview)
        aggregate, counts = {}, {}
        priority = ('unknown', 'failed', 'error', 'timeout', 'running', 'awaiting_review', 'retrying', 'blocked',
                    'interrupted', 'cancelled', 'waiting_resource', 'queued', 'pending', 'planned', 'skipped', 'passed')
        for key in self.grouped.members:
            members = self.group_keys(key)
            tally = {}
            for phase_id in members:
                state, reason = states[phase_id]
                tally[state] = tally.get(state, 0) + 1
                if phase_id in self.rows:
                    self.rows[phase_id].setText(1, 'Waiting for resource' if state == 'waiting_resource' else state.replace('_', ' '))
                    self.rows[phase_id].setToolTip(1, reason)
            state = next((state for state in priority if state in tally), next(iter(tally), 'captured' if key == 'source' else 'no_separate_subtasks'))
            aggregate[key] = dict(status=state, total=len(members),
                completed=sum(number for status, number in tally.items()
                    if status in {'passed', 'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown', 'skipped'}))
            measured = [facts[name]['seconds'] for name in members
                if facts.get(name, {}).get('seconds') is not None and states[name][0] not in {'skipped', 'blocked', 'queued', 'waiting_resource'}]
            quantity = str(len(members)) + ' subtask' + ('s' if len(members) != 1 else '')
            counts[key] = quantity if self.preview and members else (' · '.join(f'{number} {state.replace("_", " ")}' for state, number in tally.items()) if members else '')
            if not self.preview and measured:
                from .run_ui import duration
                counts[key] += '\nTotal step time: ' + duration(sum(measured)) + ' (may overlap)'
        if not self.preview:
            from .resources import resource_label
            for key in counts:
                waiting = list(dict.fromkeys(facts[name].get('resource', '') for name in self.group_keys(key)
                    if facts.get(name, {}).get('status') == 'waiting_resource' and facts[name].get('resource')))
                if waiting:
                    counts[key] += '\nWaiting: ' + ', '.join(resource_label(name) for name in waiting)
        for phase_id, row in self.rows.items():
            state, reason = states[phase_id]
            row.setText(1, 'Waiting for resource' if state == 'waiting_resource' else state.replace('_', ' '))
            row.setToolTip(1, reason)
        self.canvas.update_facts(self.grouped, aggregate, self.selected, preview=True)
        for key, text in counts.items():
            _, status_label, label = self.canvas.cards[key]
            if self.preview:
                status_label.hide()
            label.setText(text)
            label.setVisible(bool(text) and not self.preview)
            card = self.canvas.cards[key][0]
            if text:
                card.setToolTip(card.toolTip() + '\n' + text +
                    ('\nOpen this card to inspect its subtasks.' if self.preview else ''))
                card.setAccessibleDescription(card.accessibleDescription() + '\n' + text)
        self.canvas.adjustSize()
        self.map.fit_map()
        if self.pages.currentIndex() == 1 and not self.graph_mode:
            self.step_flow.set_facts(facts)
            self.show_task(self.step_flow.selected)
