"""Explicit delivery selections with the workflow's card and action hierarchy."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget)

from .ui_components import style_button, style_dialog_buttons, HeadingLabel


class EffectReviewDialog(QDialog):
    def __init__(self, text, parent=None, steps=(), *, cards=(), source='', retry_failed=None):
        super().__init__(parent)
        self.setWindowTitle('Review delivery')
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        heading = HeadingLabel('Review delivery')
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)

        def label(text, target, *, bold=False):
            widget = QLabel(text)
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            if bold:
                widget.setStyleSheet('font-weight: 600;')
            target.addWidget(widget)
            return widget

        if source:
            label('Source · ' + source, content)
        self.approvals, self.cards = {}, {}
        by_step = {card['step']: card for card in cards}
        for step in steps:
            card = by_step.get(step, dict(title=step, destinations=[], platforms=[],
                recipients=[], choices=[], builds=[]))
            frame = QFrame()
            frame.setObjectName('approvalCard')
            frame.setStyleSheet('''QFrame#approvalCard { background: palette(base);
                border: 1px solid palette(mid); border-left: 4px solid #b37c12; border-radius: 8px; }
                QFrame#approvalCard[selected="true"] { border: 2px solid palette(highlight); border-left-width: 4px; }
                QFrame#approvalCard QCheckBox { font-weight: 600; spacing: 8px; padding: 4px; }
                QFrame#approvalCard QCheckBox:focus { border: 1px dashed palette(highlight); }''')
            rows = QVBoxLayout(frame)
            rows.setContentsMargins(14, 10, 14, 12)
            title = QHBoxLayout()
            control = QCheckBox('Authorize')
            control.setAccessibleName('Authorize ' + card['title'] + ' · ' + step)
            control.setAccessibleDescription('\n'.join(card['destinations'] +
                [name + ': ' + str(value) for name, value in card['recipients'] + card['choices']] +
                [build['name'] + ' · SHA-256 ' + build['sha256'] for build in card['builds']]))
            title.addWidget(control)
            label(card['title'], title, bold=True)
            badge = QLabel('Approval required')
            badge.setStyleSheet('border: 1px solid #b37c12; border-radius: 4px; padding: 2px 5px;')
            title.addStretch()
            title.addWidget(badge)
            rows.addLayout(title)
            if card['title'].casefold() != step.casefold():
                label(step, rows)
            label('Destination · ' + ('\n'.join(card['destinations']) or 'Not declared'), rows, bold=True)
            if card['platforms']:
                label('Platforms · ' + ', '.join(card['platforms']), rows)
            for name, value in card['recipients'] + card['choices']:
                label(name + ' · ' + str(value), rows)
            if not card['recipients']:
                label('Recipients · Not declared', rows)
            label('Prepared files', rows, bold=True)
            if not card['builds']:
                label('No prerequisite artifacts recorded', rows)
            for build in card['builds']:
                item = label(build['name'] + ' · SHA-256 ' + build['sha256'][:12], rows)
                item.setToolTip(build['path'] + '\nSHA-256: ' + build['sha256'])
                from .review_ui import Disclosure
                identity = QLabel(build['path'] + '\nSHA-256: ' + build['sha256'])
                identity.setWordWrap(True)
                identity.setTextFormat(Qt.TextFormat.PlainText)
                identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                rows.addWidget(Disclosure('File path and full checksum', identity))
                for name, value in build.get('identity', ()):
                    label(name + ' · ' + str(value), rows)
            self.approvals[step], self.cards[step] = control, frame
            control.toggled.connect(lambda selected, frame=frame: self.select_card(frame, selected))
            content.addWidget(frame)
        self.evidence_toggle = QPushButton('▸ Technical evidence')
        self.evidence_toggle.setCheckable(True)
        self.evidence_toggle.setAutoDefault(False)
        self.evidence_toggle.setAccessibleName('Expand technical evidence')
        style_button(self.evidence_toggle)
        content.addWidget(self.evidence_toggle)
        self.evidence = QPlainTextEdit(text)
        self.evidence.setReadOnly(True)
        self.evidence.setAccessibleName('Retained delivery evidence for approval')
        self.evidence.setMinimumHeight(220)
        self.evidence.hide()
        content.addWidget(self.evidence)
        self.evidence_toggle.toggled.connect(self.evidence.setVisible)
        def disclose(expanded):
            self.evidence_toggle.setText(('▾' if expanded else '▸') + ' Technical evidence')
            self.evidence_toggle.setAccessibleName(
                'Collapse technical evidence' if expanded else 'Expand technical evidence')
        self.evidence_toggle.toggled.connect(disclose)
        content.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.retry_failed = None
        if retry_failed is not None:
            self.retry_failed = QCheckBox('Retry failed checks and their blocked steps')
            self.retry_failed.setChecked(retry_failed)
            self.retry_failed.setToolTip('Leave unchecked to continue selected ready actions while preserving failed and blocked branches. Unknown external outcomes are never repeated automatically.')
            layout.addWidget(self.retry_failed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve = buttons.addButton('Approve selected actions' if steps else 'Approve and continue',
            QDialogButtonBox.ButtonRole.AcceptRole)
        approve.setAutoDefault(False)
        if steps:
            approve.setEnabled(False)
            def refresh():
                count = sum(control.isChecked() for control in self.approvals.values())
                approve.setEnabled(bool(count))
                approve.setText(f'Approve {count} selected action' + ('s' if count != 1 else '')
                    if count else 'Approve selected actions')
            for control in self.approvals.values():
                control.toggled.connect(refresh)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        style_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def select_card(frame, selected):
        frame.setProperty('selected', selected)
        frame.style().unpolish(frame)
        frame.style().polish(frame)
