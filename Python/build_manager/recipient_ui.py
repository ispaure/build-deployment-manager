"""Generic checkable run recipients supplied by a project, without device access."""
import json
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QPushButton

from .run_fields import parse_multiselect_ids
from .ui_components import WrappingLayout


class RecipientPicker(QWidget):
    textChanged = Signal()
    reload_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        self.note = QLabel('Loading saved recipients…'); self.note.setWordWrap(True)
        self.items = QListWidget(); self.items.setFixedHeight(52)
        self.items.setAccessibleName('Choose deployment recipients')
        self.setFocusProxy(self.items)
        self.items.itemChanged.connect(self.selection_changed)
        layout.addWidget(self.note); layout.addWidget(self.items)
        row = WrappingLayout(); self.manual = QLineEdit()
        self.manual.setPlaceholderText('Paired device ID / Android serial')
        self.manual.setAccessibleName('Add a specific device ID')
        self.add = QPushButton('Add ID'); self.reload = QPushButton('Reload saved devices')
        self.reload.setAccessibleName('Reload saved devices')
        self.reload.setToolTip('Reload saved device metadata. This does not scan or connect to devices.')
        self.add.clicked.connect(self.add_manual); self.reload.clicked.connect(self.reload_requested)
        self.manual.returnPressed.connect(self.add_manual)
        manual_label = QLabel('Add a paired device by ID')
        manual_label.setWordWrap(True)
        manual_label.setBuddy(self.manual)
        layout.addWidget(manual_label)
        layout.addWidget(self.manual)
        row.addWidget(self.add); row.addWidget(self.reload); row.addStretch(); layout.addLayout(row)
        self.selected_count = QLabel('0 devices selected · saved metadata is not a connection check')
        self.selected_count.setWordWrap(True)
        layout.addWidget(self.selected_count)

    def size_rows(self):
        self.items.setFixedHeight((self.fontMetrics().height() + 10) * min(4, max(1, self.items.count())) + 8)
        self.selected_count.setText(str(len(parse_multiselect_ids(self.text())))
            + ' devices selected · connection checked at installation')

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, 'selected_count'):
            self.size_rows()

    def selection_changed(self, item):
        try:
            parse_multiselect_ids(self.text())
        except ValueError as error:
            self.items.blockSignals(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.items.blockSignals(False)
            self.note.setText(str(error))
            return
        self.textChanged.emit()
        self.size_rows()

    def setPlaceholderText(self, text):
        self.manual.setToolTip(text)

    def text(self):
        return json.dumps([self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())
                           if self.items.item(i).checkState() == Qt.CheckState.Checked])

    def setText(self, value):
        selected = parse_multiselect_ids(value)
        self.set_choices(self.choices(), selected)

    def choices(self):
        return [dict(id=self.items.item(i).data(Qt.ItemDataRole.UserRole), label=self.items.item(i).text())
                for i in range(self.items.count())]

    def set_choices(self, rows, selected=None):
        selected = parse_multiselect_ids(self.text()) if selected is None else selected
        names = {row['id']: row['label'] for row in rows}
        for key in selected:
            names.setdefault(key, key + ' · saved selection')
        self.items.blockSignals(True); self.items.clear()
        for key, label in names.items():
            item = QListWidgetItem(label, self.items); item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
        self.items.blockSignals(False)
        self.size_rows()
        self.note.setText('Select devices below.' if names else 'No saved devices. Add a paired, connected device ID below.')
        self.note.setToolTip('Saved status may be out of date. Connection is checked at installation; unavailable devices are never replaced with another recipient.')

    def add_manual(self):
        key = self.manual.text().strip()
        try:
            parse_multiselect_ids(json.dumps([key]))
        except ValueError as error:
            self.note.setText(str(error)); return
        selected = parse_multiselect_ids(self.text())
        if key not in selected:
            selected.append(key)
            try:
                parse_multiselect_ids(json.dumps(selected))
            except ValueError as error:
                self.note.setText(str(error)); return
        self.set_choices(self.choices(), selected); self.manual.clear(); self.textChanged.emit()
