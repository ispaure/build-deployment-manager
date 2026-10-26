"""Descriptor-only project setup. No project interpreter runs during inspection."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from .registry import inspect


def interpreter_path(root, descriptor):
    value = descriptor['interpreter']
    return Path(root) / (value[sys.platform] if isinstance(value, dict) else value)



class AddProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Add a project')
        self.resize(690, 430)
        self.root = None
        layout = QVBoxLayout(self)
        intro = QLabel('Choose the local folder containing the project you want to build or test. '
                       'Adding it allows this checkout’s local tools to load settings and prepare plans. Tests still need Start.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel('Project folder'))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText('Choose a folder or paste its full path')
        self.path.setAccessibleName('Project folder')
        browse = QPushButton('Choose folder…')
        browse.clicked.connect(self.browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self.summary = QLabel('Select a folder to see the project and its available work.')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setAccessibleName('Project setup preview')
        layout.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Project description details')
        self.details.hide()
        toggle = QPushButton('Show project description')
        toggle.clicked.connect(self.toggle_details)
        layout.addWidget(toggle)
        layout.addWidget(self.details)
        layout.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = self.buttons.addButton('Add project', QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.preview)
        self.path.textChanged.connect(self.schedule_preview)

    def toggle_details(self):
        self.details.setVisible(not self.details.isVisible())

    def schedule_preview(self, *_):
        self.timer.start()

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, 'Choose a project folder', self.path.text())
        if selected:
            self.path.setText(selected)

    def preview(self):
        self.root = None
        self.add_button.setEnabled(False)
        self.details.clear()
        try:
            if not self.path.text().strip():
                self.summary.setText('Choose a folder to begin.')
                return
            root = Path(self.path.text().strip()).expanduser().resolve()
            descriptor, _ = inspect(root)
            python = interpreter_path(root, descriptor)
            self.summary.setText(f"{descriptor['name']}\n"
                + 'Available platforms: ' + ', '.join(descriptor['capabilities']['platforms'])
                + '\n' + ('Python environment found.' if python.is_file() else
                            'Python environment is missing. You can add this project now and set up its environment before running.')
                + '\nNext: check project settings, then choose what to test.')
            self.details.setPlainText(json.dumps(descriptor, indent=2))
            self.root = root
            self.add_button.setEnabled(True)
        except (OSError, ValueError, KeyError) as error:
            self.summary.setText('This folder is not ready to add. ' + str(error)
                + '\nChoose the project root containing build-project.json.')

    def accept(self):
        self.preview()
        if self.root is not None:
            super().accept()
