"""Generic checkable run recipients supplied by a project, without device access."""
import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QPushButton

from .run_fields import selection_ids


class RecipientPicker(QWidget):
    textChanged = Signal()
    reload_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.note = QLabel('Loading saved recipients…'); self.note.setWordWrap(True)
        self.items = QListWidget(); self.items.setFixedHeight(52)
        self.items.setAccessibleName('Choose deployment recipients')
        self.setFocusProxy(self.items)
        self.items.itemChanged.connect(lambda *_: self.textChanged.emit())
        layout.addWidget(self.note); layout.addWidget(self.items)
        row = QHBoxLayout(); self.manual = QLineEdit()
        self.manual.setPlaceholderText('Paired device ID / Android serial')
        self.manual.setAccessibleName('Add a specific device ID')
        self.add = QPushButton('Add ID'); self.reload = QPushButton('Reload')
        self.reload.setAccessibleName('Reload saved devices')
        self.reload.setToolTip('Reload saved device metadata. This does not scan or connect to devices.')
        self.add.clicked.connect(self.add_manual); self.reload.clicked.connect(self.reload_requested)
        self.manual.returnPressed.connect(self.add_manual)
        row.addWidget(self.manual); row.addWidget(self.add); row.addWidget(self.reload); layout.addLayout(row)

    def setPlaceholderText(self, text):
        self.manual.setToolTip(text)

    def text(self):
        return json.dumps([self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())
                           if self.items.item(i).checkState() == Qt.CheckState.Checked])

    def setText(self, value):
        selected = selection_ids(value)
        self.set_choices(self.choices(), selected)

    def choices(self):
        return [dict(id=self.items.item(i).data(Qt.ItemDataRole.UserRole), label=self.items.item(i).text())
                for i in range(self.items.count())]

    def set_choices(self, rows, selected=None):
        selected = selection_ids(self.text()) if selected is None else selected
        names = {row['id']: row['label'] for row in rows}
        for key in selected:
            names.setdefault(key, key + ' · saved selection')
        self.items.blockSignals(True); self.items.clear()
        for key, label in names.items():
            item = QListWidgetItem(label, self.items); item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
        self.items.blockSignals(False)
        self.items.setFixedHeight(22 * min(4, max(1, len(names))) + 8)
        self.note.setText('Select devices below.' if names else 'No saved devices. Add a paired, connected device ID below.')
        self.note.setToolTip('Saved status may be out of date. Connection is checked at installation; unavailable devices are never replaced with another recipient.')

    def add_manual(self):
        key = self.manual.text().strip()
        try:
            selection_ids(json.dumps([key]))
        except ValueError as error:
            self.note.setText(str(error)); return
        selected = selection_ids(self.text())
        if key not in selected:
            selected.append(key)
        self.set_choices(self.choices(), selected); self.manual.clear(); self.textChanged.emit()
