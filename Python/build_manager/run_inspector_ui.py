"""Selected-phase presentation with explicit plan/facts and stable text selection."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class RunInspectorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.selection_heading = QLabel('Whole workflow')
        self.selection_heading.setStyleSheet('font-weight: 600; font-size: 14pt;')
        self.selection_info = QLabel('Select a workflow card to inspect its progress, tests, timing and output.')
        self.next_action = QLabel()
        for control in (self.selection_heading, self.selection_info, self.next_action):
            control.setTextFormat(Qt.TextFormat.PlainText)
            control.setWordWrap(True)
        layout.addWidget(self.selection_heading)
        layout.addWidget(self.selection_info)
        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName('Selected step details and evidence')
        self.detail_key = None

    def show_group(self, heading, information, details):
        self.selection_heading.setText(heading)
        self.selection_info.setText(information)
        self.set_detail_text(details, '')

    def show_phase(self, plan, phase, fact, state, reason, phases):
        from .workflow_presentation import title, effect_label
        self.selection_heading.setText(title(phase))
        dependencies = ', '.join(title(phases[key]) for key in phase.dependencies) or 'None'
        from .workflow_presentation import state_label, step_time
        text = f'{effect_label(phase, plan)} · {state_label(state)}\nPrerequisites: {dependencies}'
        if reason:
            text += '\n' + reason
        elapsed = step_time(fact, state)
        if elapsed:
            text += '\n' + ('Running for: ' if state == 'running' else 'Step duration: ') + elapsed
        if getattr(phase, 'waits_for', ()):
            text += '\nWaits for completion (success not required): ' + ', '.join(phase.waits_for)
        if phase.resources:
            from .resources import resource_details
            text += '\n' + '\n'.join(resource_details(plan, phase.id))
        for row in getattr(plan, 'journey', {}).get('destinations', {}).values():
            if phase.id in row['steps']:
                text += '\nDestination: ' + row['identity']
        self.selection_info.setText(text)
        if state in {'blocked', 'skipped'}:
            self.next_action.setText('This step will not run. ' + reason + '\nSelect its prerequisite cards to inspect the cause.')
        elif state == 'waiting_resource':
            self.next_action.setText(reason + '\nOther independent platform steps can continue.')
        elif state == 'retrying':
            self.next_action.setText('Waiting to reconnect automatically. Other work continues; completed tests and prepared builds are retained. Stop cancels the wait.')
        elif state == 'running':
            self.next_action.setText('This step is running. Reports appear after capture; Output shows its current messages.')
        elif state == 'passed':
            self.next_action.setText('This step passed. Results and timing below belong to this card. Other branches may still be running.')
        elif state in {'failed', 'error', 'timeout'}:
            self.next_action.setText('This step failed. Inspect Tests for failures or Details and Output for the reason.')
        elif state == 'awaiting_review':
            self.next_action.setText('This step needs your approval. Use Review and continue below the workflow to inspect the exact action before it starts.')
        elif state == 'unknown':
            self.next_action.setText('This step has an unknown outcome. Check its provider status before retrying; it will not repeat automatically.')
        else:
            self.next_action.setText(reason or 'This step has not produced a report. Inspect Details for its current state.')

    def set_detail_text(self, text, key):
        if self.detail.toPlainText() != text:
            cursor = self.detail.textCursor()
            position, anchor = cursor.position(), cursor.anchor()
            bar = self.detail.verticalScrollBar()
            offset = bar.value()
            same = getattr(self, 'detail_key', None) == key
            self.detail.setPlainText(text)
            if same:
                last = self.detail.document().characterCount() - 1
                cursor.setPosition(min(anchor, last))
                cursor.setPosition(min(position, last), cursor.MoveMode.KeepAnchor)
                self.detail.setTextCursor(cursor)
                bar.setValue(offset)
        self.detail_key = key

