"""Descriptor-only project setup. No project interpreter runs during inspection."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from .registry import read_project_descriptor
from .ui_components import style_dialog_buttons, style_utilities


def interpreter_path(root, descriptor):
    if 'commands' in descriptor:
        return Path(sys.executable)
    value = descriptor['interpreter']
    return Path(root) / (value[sys.platform] if isinstance(value, dict) else value)



class AddProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Add a project')
        self.resize(690, 360)
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
        layout.addWidget(QLabel('Registration name · optional'))
        self.registration_name = QLineEdit()
        self.registration_name.setAccessibleName('Registration name')
        self.registration_name.setPlaceholderText('Defaults to the project name. Use a unique name for a worktree.')
        layout.addWidget(self.registration_name)
        name_help = QLabel('Leave blank to use the project name. Give a worktree its own recognizable name.')
        name_help.setWordWrap(True)
        layout.addWidget(name_help)
        self.summary = QLabel('Select a folder to see the project and its available work.')
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setAccessibleName('Project setup preview')
        layout.addWidget(self.summary)
        layout.insertWidget(layout.indexOf(self.registration_name) - 1, self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Project description details')
        self.details.hide()
        self.description_toggle = QPushButton('Show project description')
        self.description_toggle.clicked.connect(self.toggle_details)
        layout.addWidget(self.description_toggle)
        layout.addWidget(self.details)
        layout.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add_button = self.buttons.addButton('Add project', QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        style_dialog_buttons(self.buttons)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.preview)
        self.path.textChanged.connect(self.schedule_preview)
        style_utilities(self)

    def toggle_details(self):
        self.details.setVisible(not self.details.isVisible())
        self.description_toggle.setText('Hide project description' if self.details.isVisible() else 'Show project description')

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
            descriptor, _ = read_project_descriptor(root)
            python = interpreter_path(root, descriptor)
            from .onboarding import readiness
            ready = readiness(root)
            self.summary.setText(f"{descriptor['name']}\n"
                + 'Available platforms: ' + ', '.join(descriptor['capabilities']['platforms'])
                + '\n' + ('Built-in command project; no Python bridge required.' if 'commands' in descriptor else 'Python environment found.' if python.is_file() else
                            'Python environment is missing. You can add this project now and set up its environment before running.')
                + '\n' + ready['message']
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
