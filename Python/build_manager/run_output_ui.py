"""Bounded execution output, projected through an explicit selected log scope."""
from collections import deque
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class RunOutputView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines = deque(maxlen=6000)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setAccessibleName('Live redacted execution output')
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
        self.log.setPlainText('\n'.join(lines) if any(lines) else 'No captured output for this selection yet. Retained log paths appear in Details.')

    def reset(self):
        self.lines.clear()
        self.log.clear()
