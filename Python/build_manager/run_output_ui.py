"""Bounded execution logs and explicit evidence availability for the selected scope."""
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .diagnostics import EvidenceRead


_TRUNCATION_NOTICE = '\nPreview truncated; open the results folder for the complete log.'
_LOG_STATUS = {
    'missing': 'The recorded log file is missing. It may have been removed from the results folder.',
    'empty': 'The retained log is empty.',
    'unreadable': 'The retained log could not be read.',
    'truncated': 'Showing a bounded log preview. The cause may appear later in the full retained log.',
    'unavailable': 'No log was recorded for this step.',
}


class RunOutputView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines = deque(maxlen=6000)
        self.dropped = set()
        self.scope_identity = None
        self.cached_log = None
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(6000)
        self.log.setAccessibleName('Redacted execution logs')
        self.log.setPlaceholderText('No captured output for this selection.')
        self.scope_label = 'Logs for the whole workflow.'
        self.notice = QLabel(self.scope_label)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.notice)
        layout.addWidget(self.log)

    def append(self, phase, text, *, selected, keys):
        lines = text.splitlines()
        for line in lines:
            if len(self.lines) == self.lines.maxlen:
                self.dropped.add(self.lines[0][0])
            self.lines.append((phase, line))
        if lines and (phase in keys or phase is None and not selected):
            if self.notice.text() != self.scope_label:
                self.notice.setText(self.scope_label)
            self.log.appendPlainText('\n'.join(('[' + phase + '] ' if phase and not selected else '') + line for line in lines))
            if self.dropped.intersection(keys) or not selected and None in self.dropped:
                self.notice.setText(self.scope_label + ' Showing recent live output. Earlier lines exceeded the buffer.')

    def read_step(self, key, reference, reader):
        if not reference:
            return EvidenceRead('', 'unavailable')
        identity = (key, reference, reader)
        if self.cached_log is not None and self.cached_log[0] == identity:
            return self.cached_log[1]
        try:
            result = reader(key) if reader else EvidenceRead('', 'unreadable')
        except FileNotFoundError:
            result = EvidenceRead('', 'missing')
        except (OSError, ValueError, TypeError):
            result = EvidenceRead('', 'unreadable')
        if isinstance(result, str):
            truncated = result.endswith(_TRUNCATION_NOTICE)
            result = EvidenceRead(result.removesuffix(_TRUNCATION_NOTICE),
                'truncated' if truncated else 'available' if result else 'empty', truncated)
        self.cached_log = (identity, result)
        return result

    def show_scope(self, *, selected, keys, reader=None, reference=None, terminal=False, card=False,
                   retained_steps=False):
        identity = (selected, frozenset(keys))
        lines = [('[' + key + '] ' if key and not selected else '') + text
                 for key, text in self.lines if key in keys or key is None and not selected]
        self.scope_label = ('Logs for the selected step.' if selected else
                            'Logs for this card and the runner.' if card else 'Logs for the workflow and the runner.')
        notice = self.scope_label
        dropped = self.dropped.intersection(keys) or not selected and None in self.dropped
        if selected and terminal:
            evidence = self.read_step(selected, reference, reader)
            if not lines or dropped and evidence.text:
                lines = [evidence.text] if evidence.text else []
                dropped = False
            status = _LOG_STATUS.get(evidence.status)
            if status and (evidence.status != 'unavailable' or not lines):
                notice += ' ' + status
        if dropped:
            notice += ' Showing recent live output. Earlier lines exceeded the buffer.'
        if not selected and retained_steps:
            notice += ' Select a step to read its retained log.'
        elif not any(lines) and not terminal:
            notice += ' Captured output will appear here as the work runs.'
        elif not selected and not any(lines):
            notice += ' No runner output was captured.'
        self.notice.setText(notice)
        text = '\n'.join(lines) if any(lines) else ''
        if text == self.log.toPlainText() and identity == self.scope_identity:
            return
        same = identity == self.scope_identity
        cursor = self.log.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        bar = self.log.verticalScrollBar()
        scroll, follow = bar.value(), bar.value() == bar.maximum()
        self.log.setPlainText(text)
        if same:
            end = self.log.document().characterCount() - 1
            cursor.setPosition(min(anchor, end))
            cursor.setPosition(min(position, end), QTextCursor.MoveMode.KeepAnchor)
            self.log.setTextCursor(cursor)
            bar.setValue(bar.maximum() if follow else scroll)
        self.scope_identity = identity

    def reset(self):
        self.lines.clear()
        self.dropped.clear()
        self.scope_identity = self.cached_log = None
        self.scope_label = 'Logs for the whole workflow.'
        self.notice.setText(self.scope_label)
        self.log.clear()
