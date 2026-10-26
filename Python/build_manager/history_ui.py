"""Searchable retained-run inventory; opening and continuation stay with the panel."""
from datetime import datetime
from pathlib import PurePath
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from .run_ui import duration
from .ui_components import search_shortcut


class RunHistoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a saved run…')
        self.search.setAccessibleName('Search saved runs')
        self.search.setClearButtonEnabled(True)
        self.find = search_shortcut(self, self.search)
        self.filter = QComboBox()
        self.filter.setAccessibleName('Saved run status filter')
        for label, key in [('All runs', 'all'), ('Needs attention', 'attention'), ('Completed', 'completed')]:
            self.filter.addItem(label, key)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.filter)
        layout.addLayout(controls)
        self.hint = QLabel('Loading saved runs…')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Started', 'Operation', 'Outcome', 'Active time', 'Next step'])
        self.tree.setAccessibleName('Project run history')
        self.tree.setColumnWidth(0, 200)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.apply_filter)
        self.filter.currentIndexChanged.connect(self.apply_filter)

    def set_rows(self, rows):
        current = self.tree.currentItem()
        path = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.tree.clear()
        labels = {'passed': 'Completed', 'awaiting_review': 'Needs approval', 'unknown': 'Unknown outcome',
            'failed': 'Failed', 'cancelled': 'Cancelled', 'running': 'Recorded running', 'queued': 'Not started'}
        actions = {'passed': 'View results', 'awaiting_review': 'Review delivery', 'unknown': 'Check provider',
            'failed': 'Inspect failure', 'cancelled': 'Inspect interruption'}
        for row in rows:
            started = row.get('started_at', '')
            try:
                started = datetime.fromisoformat(started).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
            except ValueError:
                pass
            state = row['status']
            item = QTreeWidgetItem([started or PurePath(row['path']).parent.name, row.get('operation', ''),
                labels.get(state, state), duration(row.get('seconds')), actions.get(state, 'Inspect record')])
            item.setData(0, Qt.ItemDataRole.UserRole, row['path'])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, state)
            item.setToolTip(0, row['path'])
            icon = (QStyle.StandardPixmap.SP_DialogApplyButton if state == 'passed' else
                QStyle.StandardPixmap.SP_MessageBoxCritical if state in {'failed', 'unknown', 'unreadable'}
                else QStyle.StandardPixmap.SP_MessageBoxWarning)
            item.setIcon(2, self.style().standardIcon(icon))
            self.tree.addTopLevelItem(item)
            if row['path'] == path:
                self.tree.setCurrentItem(item)
        self.apply_filter()

    def apply_filter(self):
        query = self.search.text().strip().casefold()
        choice = self.filter.currentData()
        visible = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            passed = item.data(0, Qt.ItemDataRole.UserRole + 1) == 'passed'
            text = ' '.join(item.text(column) for column in range(item.columnCount())) + ' ' + item.toolTip(0)
            match = query in text.casefold() and (choice == 'all' or passed == (choice == 'completed'))
            item.setHidden(not match)
            visible += bool(match)
            if not match and item is self.tree.currentItem():
                self.tree.setCurrentItem(None)
        total = self.tree.topLevelItemCount()
        self.hint.setText(f'{visible} of {total} saved runs' if visible else
            'No matching runs' if total else 'No saved runs yet')
