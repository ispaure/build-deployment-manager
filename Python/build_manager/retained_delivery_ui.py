"""Declared recipients/options for a fresh delivery from a selected saved run."""
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
    QScrollArea, QVBoxLayout, QWidget)

from .run_fields_ui import RunFieldsView
from .ui_components import style_dialog_buttons


class RetainedDeliveryDialog(QDialog):
    def __init__(self, project, run_directory, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Prepare delivery from saved run')
        self.resize(720, 600)
        layout = QVBoxLayout(self)
        label = QLabel('Reuse verified saved inputs with new delivery choices. '
            'The project checks the selected platform’s gates and retained files. '
            'Review the new plan before starting; this does not install or deliver anything.')
        label.setWordWrap(True); layout.addWidget(label)
        path = QLabel(str(run_directory)); path.setTextFormat(Qt.TextFormat.PlainText)
        path.setWordWrap(True); layout.addWidget(path)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); content = QVBoxLayout(body)
        self.destinations = {}
        for name, row in (project.journey_capability or {}).get('destinations', {}).items():
            control = QCheckBox(row.get('label', name)); control.setToolTip(name)
            control.toggled.connect(self.update_choices)
            self.destinations[name] = control; content.addWidget(control)
        # Reuse ordinary saved recipient/choice controls, excluding test workflow options.
        inputs = dict(run_fields=[row for row in project.run_fields if row.get('destinations')])
        for name in ('run_defaults', 'run_choices'):
            if hasattr(project, name): inputs[name] = getattr(project, name)
        self.fields = RunFieldsView(SimpleNamespace(**inputs))
        content.addWidget(self.fields); content.addStretch()
        scroll.setWidget(body); layout.addWidget(scroll)
        self.message = QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.prepare = buttons.addButton('Prepare review plan', QDialogButtonBox.ButtonRole.AcceptRole)
        self.prepare.setEnabled(False); self.prepare.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        style_dialog_buttons(buttons); layout.addWidget(buttons)
        self.finished.connect(lambda _: self.fields.stop())
        self.update_choices()

    def choices(self):
        return dict(destinations=[name for name, control in self.destinations.items() if control.isChecked()],
                    run_overrides=self.fields.values())

    def update_choices(self, *_):
        if not hasattr(self, 'fields'): return
        destinations = [name for name, control in self.destinations.items() if control.isChecked()]
        self.fields.update_context('deliver', destinations, '')
        self.prepare.setEnabled(bool(destinations))

    def accept(self):
        if not self.choices()['destinations']:
            self.message.setText('Choose at least one delivery destination.')
            return
        missing = self.fields.missing_selection()
        if missing:
            self.message.setText(missing)
            return
        super().accept()
