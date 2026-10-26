"""Familiar journey cards with an in-place desktop subtask browser."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QSizePolicy)
from .grouped_workflow import group_workflow
from .plan_summary import captured_choices, phase_title, summary_rows
from .workflow_ui import FlowCanvas, FitMapView, display_states, effect_label, blocking_prerequisite
from .ui_components import style_button, ViewportStack


class GroupedFlowView(QWidget):
    phase_selected = Signal(str)
    blocker_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan, self.selected, self.facts = None, '', {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = ViewportStack()
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        overview = QWidget()
        body = QVBoxLayout(overview)
        body.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.additional = QPushButton()
        self.additional.clicked.connect(lambda: self.open_group('__unassigned__'))
        toolbar.addWidget(self.additional)
        toolbar.addStretch()
        self.canvas = FlowCanvas()
        self.canvas.selected.connect(self.open_group)
        self.map = FitMapView(self.canvas)
        self.map.setMinimumHeight(180)
        for title, callback in [('Fit', self.fit), ('+', lambda: self.map.zoom(1.2)), ('−', lambda: self.map.zoom(1 / 1.2))]:
            button = QPushButton(title)
            button.setAccessibleName({'Fit': 'Fit readable cards', '+': 'Zoom in', '−': 'Zoom out'}[title])
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
        self.tasks = QTreeWidget()
        self.tasks.setHeaderLabels(['Subtask', 'State', 'Purpose'])
        self.tasks.setAccessibleName('Exact subtasks inside the selected workflow card')
        self.tasks.setColumnWidth(0, 210)
        self.tasks.setColumnWidth(1, 170)
        self.tasks.setWordWrap(True)
        self.tasks.currentItemChanged.connect(self.show_task)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Selected card or subtask details')
        self.splitter = QSplitter()
        self.splitter.addWidget(self.tasks)
        self.splitter.addWidget(self.details)
        self.splitter.setSizes([500, 450])
        inner.addWidget(self.splitter, 1)
        self.inspect = QPushButton('Inspect selected step in full workflow…')
        self.inspect.clicked.connect(self.inspect_task)
        self.blocker = style_button(QPushButton('View blocking step'))
        self.blocker.clicked.connect(lambda: self.blocker_selected.emit(self.blocking_key) if self.blocking_key else None)
        self.blocking_key = ''
        self.blocker.hide()
        actions = QHBoxLayout()
        actions.addWidget(self.blocker)
        actions.addStretch()
        actions.addWidget(self.inspect)
        inner.addLayout(actions)
        self.pages.addWidget(inside)
        layout.addWidget(self.pages, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fit)
        self.rows = {}

    def reset(self, plan, fields=(), *, preview=True, capability=None, proposal=None):
        self.plan, self.fields, self.preview = plan, fields, preview
        self.grouped = group_workflow(plan, capability, proposal)
        self.phases = {phase.id: phase for phase in plan.phases}
        self.additional.setText(f'Other resolved subtasks ({len(self.grouped.unassigned)})…')
        self.additional.setVisible(bool(self.grouped.unassigned))
        self.selected, self.facts = '', {}
        self.rows = {}
        self.tasks.clear()
        self.details.clear()
        self.pages.setCurrentIndex(0)
        self.canvas.reset(self.grouped)
        self.map.reset_view()
        self.set_facts({})
        self.timer.start(0)

    def fit(self):
        self.map.fit_mode = True
        self.map.fit_map(force=True)

    def open_group(self, key):
        self.selected = key
        node = next((node for node in self.grouped.phases if node.id == key), None)
        keys = self.group_keys(key)
        self.heading.setText((node.label if node else 'Other resolved subtasks') + ' · ' + str(len(keys)) + ' exact subtask' + ('s' if len(keys) != 1 else ''))
        self.tasks.blockSignals(True)
        self.tasks.clear()
        self.rows = {}
        for phase_id in keys:
            phase = self.phases[phase_id]
            row = QTreeWidgetItem([phase_title(phase), '', effect_label(phase, self.plan)])
            row.setData(0, Qt.ItemDataRole.UserRole, phase_id)
            self.tasks.addTopLevelItem(row)
            self.rows[phase_id] = row
        self.tasks.blockSignals(False)
        self.pages.setCurrentIndex(1)
        self.set_facts(self.facts)
        self.show_task(None)
        self.inspect.setEnabled(False)
        if keys:
            self.tasks.setCurrentItem(self.rows[keys[0]])
            self.tasks.setFocus()
        else:
            self.details.setFocus()

    def group_keys(self, key):
        if key == '__unassigned__':
            return self.grouped.unassigned
        return tuple(dict.fromkeys((*self.grouped.members[key], *self.grouped.references.get(key, ()))))

    def close_group(self):
        key = self.selected
        self.pages.setCurrentIndex(0)
        self.set_facts(self.facts)
        self.timer.start(0)
        if key in self.canvas.cards:
            self.canvas.cards[key][0].setFocus()

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
            lines.append('Subtasks are listed in plan order. Their prerequisites determine which can overlap.')
        for row in later:
            if keys.intersection(row['keys']):
                lines.append(row['detail'])
        if shared:
            lines += ['Shared captured values:', *shared]
        return '\n\n'.join(lines)

    def show_task(self, row, previous=None):
        key = row.data(0, Qt.ItemDataRole.UserRole) if row else ''
        self.inspect.setEnabled(bool(key))
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, key) if key and not self.preview else ''
        self.blocker.setVisible(bool(self.blocking_key))
        lines = [self.group_context()]
        if key:
            phase = self.phases[key]
            state, reason = display_states(self.plan, self.facts, self.preview)[key]
            lines += [phase_title(phase), 'State: ' + state.replace('_', ' '), effect_label(phase, self.plan),
                      'Prerequisites: ' + (', '.join(phase_title(self.phases[parent]) for parent in phase.dependencies) or 'None')]
            if reason:
                lines.append(reason)
            if getattr(phase, 'waits_for', ()):
                lines.append('Waits for completion: ' + ', '.join(phase.waits_for))
            from .resources import resource_details
            lines.extend(resource_details(self.plan, key))
            lines += ['Required: ' + ('Yes' if phase.required else 'No'), 'Timeout: ' + str(phase.timeout) + ' seconds']
            if phase.artifacts:
                lines += ['Declared outputs:', *phase.artifacts]
        lines.append('Opening cards and subtasks starts no commands.')
        self.details.setPlainText('\n\n'.join(filter(None, lines)))

    def inspect_task(self):
        row = self.tasks.currentItem()
        if row:
            self.phase_selected.emit(row.data(0, Qt.ItemDataRole.UserRole))

    def set_facts(self, facts):
        self.facts = facts
        if self.plan is None:
            return
        states = display_states(self.plan, facts, self.preview)
        aggregate, counts = {}, {}
        priority = ('unknown', 'failed', 'error', 'timeout', 'running', 'awaiting_review', 'blocked',
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
            aggregate[key] = dict(status=state)
            quantity = str(len(members)) + ' subtask' + ('s' if len(members) != 1 else '')
            counts[key] = quantity if self.preview and members else (' · '.join(f'{number} {state.replace("_", " ")}' for state, number in tally.items()) if members else '')
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
            if self.preview and text:
                card.setToolTip(card.toolTip() + '\n' + text + '\nOpen this card to inspect its subtasks.')
                card.setAccessibleDescription(card.accessibleDescription() + '\n' + text)
            card.setMinimumHeight(max(64, card.layout().totalHeightForWidth(card.width())))
        self.canvas.adjustSize()
        self.map.fit_map()
        if self.pages.currentIndex() == 1:
            self.show_task(self.tasks.currentItem())
