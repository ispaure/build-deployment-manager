"""Source-choice widgets and revision synchronization, independent of project policy."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget


class SourceSelectionView(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._syncing_source = False
        self._custom_revision = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.source_mode = QComboBox()
        self.source_mode.setAccessibleName('Source to build')
        self.source_mode.addItem('Current files — include uncommitted edits', 'working-tree')
        self.source_mode.addItem('Latest commit — exclude uncommitted edits', 'HEAD')
        self.source_mode.addItem('Specific commit, branch or tag', 'custom')
        self.revision = QLineEdit('working-tree')
        self.revision.setAccessibleName('Specific source revision')
        self.revision.setPlaceholderText('Commit SHA, branch or tag')
        self.source_form = QFormLayout()
        self.source_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.source_form.addRow('Build from', self.source_mode)
        self.source_form.addRow('Revision', self.revision)
        self.source_form.setRowVisible(self.revision, False)
        layout.addLayout(self.source_form)
        self.source_summary = QLabel()
        self.source_summary.setWordWrap(True)
        self.source_summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.source_summary)
        self.source_mode.currentIndexChanged.connect(self.choose_source)
        self.revision.textChanged.connect(self.source_revision_changed)

    def choose_source(self, *_):
        if self._syncing_source:
            return
        value = self.source_mode.currentData()
        self._syncing_source = True
        try:
            if value != 'custom':
                self.revision.setText(value)
            elif self.revision.text() in ('working-tree', 'HEAD'):
                self.revision.setText(self._custom_revision)
        finally:
            self._syncing_source = False
        self.source_form.setRowVisible(self.revision, value == 'custom')
        self.changed.emit()

    def source_revision_changed(self, *_):
        if not self._syncing_source and not (self.source_mode.currentData() == 'custom' and self.revision.hasFocus()):
            self._syncing_source = True
            try:
                value = self.revision.text()
                self.source_mode.setCurrentIndex(self.source_mode.findData(value if value in ('working-tree', 'HEAD') else 'custom'))
            finally:
                self._syncing_source = False
            self.source_form.setRowVisible(self.revision, self.source_mode.currentData() == 'custom')
        if self.source_mode.currentData() == 'custom' and self.revision.text() not in ('working-tree', 'HEAD'):
            self._custom_revision = self.revision.text()
        self.changed.emit()
