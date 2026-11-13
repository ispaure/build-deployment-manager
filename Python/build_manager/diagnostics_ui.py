"""Explicit local diagnostic preview, isolated clipboard boundary and recovery offer."""
from queue import Empty, Queue
from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


class _PreviewJob(QRunnable):
    def __init__(self, factory, results):
        super().__init__()
        self.factory, self.results = factory, results

    def run(self):
        try:
            self.results.put((self.factory(True), self.factory(False)))
        except Exception:
            # File/format errors must not echo an unsanitized exception.
            self.results.put(('Diagnostic preview unavailable. Existing evidence is unchanged.',) * 2)


class DiagnosticPreview(QDialog):
    """The two frozen variants are generated from a caller-owned immutable snapshot.

    Workers retain only the factory and queue, never a widget. Close invalidates
    delivery even when a slow read is still retiring.
    """
    def __init__(self, text_factory, parent=None, *, clipboard=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('Copy diagnostics')
        self.resize(760, 560)
        self.results, self.variants = Queue(), None
        self.retired = False
        self.write_clipboard = (lambda text: QApplication.clipboard().setText(text)) if clipboard is None else clipboard
        layout = QVBoxLayout(self)
        note = QLabel('Review this redacted text before copying it for manual sharing. Only the preview is copied.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.include_excerpt = QCheckBox('Include log or traceback excerpt')
        self.include_excerpt.setChecked(True)
        self.include_excerpt.toggled.connect(self.update_preview)
        layout.addWidget(self.include_excerpt)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName('Exact diagnostic clipboard preview')
        self.preview.setPlainText('Preparing bounded diagnostic preview…')
        layout.addWidget(self.preview, 1)
        self.feedback = QLabel('Nothing has been copied.')
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        self.copy_button = buttons.addButton('Copy', QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.receive)
        self.timer.start()
        QThreadPool.globalInstance().start(_PreviewJob(text_factory, self.results))

    def receive(self):
        if self.retired:
            return
        try:
            self.variants = self.results.get_nowait()
        except Empty:
            return
        self.timer.stop()
        self.update_preview()
        self.copy_button.setEnabled(True)

    def update_preview(self, *_):
        if self.variants and not self.retired:
            self.preview.setPlainText(self.variants[0 if self.include_excerpt.isChecked() else 1])
            self.feedback.setText('Nothing has been copied from this preview.')

    def copy(self):
        if self.variants and not self.retired:
            try:
                self.write_clipboard(self.preview.toPlainText())
            except Exception:
                self.feedback.setText('Could not copy. You can select the preview text manually.')
            else:
                self.feedback.setText('Copied. Paste it where you choose to share it.')

    def closeEvent(self, event):
        self.retired = True
        self.timer.stop()
        super().closeEvent(event)


def offer_manager_diagnostics(window, store, records, warning=''):
    """Nonmodal startup notice. Inspection/dismissal has no run-side effects."""
    from .diagnostics import format_diagnostics
    from .manager_diagnostics import DiagnosticUnavailable
    from copy import deepcopy
    if not records and not warning:
        return
    panel = QWidget(window)
    panel.setObjectName('managerDiagnosticOffer')
    layout = QVBoxLayout(panel)
    if warning:
        label = QLabel(warning)
        label.setWordWrap(True)
        layout.addWidget(label)
    if records:
        text = QLabel('Previous manager sessions have local diagnostics. Run outcomes must be inspected separately.')
        text.setWordWrap(True)
        layout.addWidget(text)
        actions = QHBoxLayout()
        picker = QComboBox()
        picker.setAccessibleName('Previous manager diagnostic')
        for original in records:
            label = 'Manager error' if original['state'] == 'error' else 'Unexpected end · cause unavailable'
            picker.addItem(label + ' · ' + original['started_at'][:19], deepcopy(original))
        actions.addWidget(picker, 1)
        inspect = QPushButton('Inspect diagnostics…')
        dismiss = QPushButton('Dismiss diagnostic')
        actions.addWidget(inspect)
        actions.addWidget(dismiss)
        def preview():
            record = picker.currentData()
            if not record:
                return
            context = dict(origin='Manager error', project='Not recorded', run_id=record['id'],
                error=record['message'], exception=record['exception'], traceback=record['stack'],
                evidence_status='Manager diagnostics only. Run outcomes must be inspected separately.')
            dialog = DiagnosticPreview(lambda include: format_diagnostics(None, context=context, include_excerpt=include), window)
            dialog.show()
        def remove():
            record = picker.currentData()
            if not record:
                return
            try:
                store.dismiss(record['id'])
            except (DiagnosticUnavailable, OSError):
                text.setText('This diagnostic could not be dismissed. It may belong to an active session.')
            else:
                picker.removeItem(picker.currentIndex())
                if picker.count() == 0:
                    panel.hide()
                    panel.deleteLater()
        inspect.clicked.connect(preview)
        dismiss.clicked.connect(remove)
        layout.addLayout(actions)
    # ManagerWindow retains a public `layout` attribute; call the Qt base
    # accessor so this also works with ordinary QWidget fixture parents.
    QWidget.layout(window).insertWidget(0, panel)
