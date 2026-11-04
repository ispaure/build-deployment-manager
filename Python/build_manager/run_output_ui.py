"""Bounded execution output, projected through an explicit selected log scope."""
from collections import deque
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class RunOutputView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines = deque(maxlen=6000)
        self.scope_identity = None
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setAccessibleName('Live redacted execution output')
        self.log.setPlaceholderText('No captured output for this selection yet. Retained log paths appear in Details.')
        self.notice = QLabel('Output for the whole workflow.')
        self.notice.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.notice)
        layout.addWidget(self.log)

    def append(self, phase, text, *, selected, keys):
        for line in text.splitlines():
            self.lines.append((phase, line))
            if phase in keys or phase is None and not selected:
                self.log.appendPlainText(('[' + phase + '] ' if phase and not selected else '') + line)

    def show_scope(self, *, selected, keys, reader=None):
        lines = [('[' + key + '] ' if key and not selected else '') + text
                 for key, text in self.lines if key in keys or key is None and not selected]
        self.notice.setText('Output for the selected step.' if selected else 'Output for steps in this card, with runner messages.')
        if selected and not lines and reader:
            try:
                lines = [reader(selected)]
            except (OSError, ValueError):
                lines = []
        text = '\n'.join(lines) if any(lines) else ''
        identity = (selected, frozenset(keys))
        if text == self.log.toPlainText() and identity == self.scope_identity:
            return
        same = identity == self.scope_identity
        cursor = self.log.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        bar = self.log.verticalScrollBar()
        scroll, follow = bar.value(), bar.value() == bar.maximum()
        self.log.setPlainText(text)
        if same:
            cursor = self.log.textCursor()
            end = self.log.document().characterCount() - 1
            cursor.setPosition(min(anchor, end))
            cursor.setPosition(min(position, end), QTextCursor.MoveMode.KeepAnchor)
            self.log.setTextCursor(cursor)
            bar.setValue(bar.maximum() if follow else scroll)
        self.scope_identity = identity

    def reset(self):
        self.lines.clear()
        self.scope_identity = None
        self.log.clear()
