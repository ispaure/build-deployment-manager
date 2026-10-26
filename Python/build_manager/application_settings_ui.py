"""Application preferences, distinct from project-owned settings."""
from pathlib import Path
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout)
from .profiles import load_profile, save_profile
from .registry import config_directory


def preferences_path(project=None):
    registry = getattr(project, 'registry', None)
    return Path(getattr(registry, 'directory', config_directory())) / 'appearance.json'


def apply_preferences(app, path):
    values = load_profile(path)
    size = values.get('text_size', 0)
    if type(size) is not int or not 0 <= size <= 28:
        raise ValueError('Text size must be between 0 and 28.')
    if not hasattr(app, '_manager_default_font'):
        app._manager_default_font = QFont(app.font())
    font = QFont(app._manager_default_font)
    if size:
        font.setPointSize(size)
    app.setFont(font)


class ApplicationSettingsDialog(QDialog):
    def __init__(self, project=None, parent=None, *, directory=None):
        super().__init__(parent)
        self.setWindowTitle('App settings')
        self.resize(580, 430)
        self.path = Path(directory) / 'appearance.json' if directory is not None else preferences_path(project)
        layout = QVBoxLayout(self)
        intro = QLabel('Application appearance applies to all projects. Build tools, signing and destinations belong in Project settings.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.size = QSpinBox()
        self.size.setRange(0, 28)
        self.size.setSpecialValueText('System default')
        self.size.setSuffix(' pt')
        form.addRow('Text size', self.size)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        try:
            size = load_profile(self.path).get('text_size', 0)
            if type(size) is not int or not 0 <= size <= 28:
                raise ValueError('Text size must be between 0 and 28.')
            self.size.setValue(size)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
        if project is not None:
            scope = QLabel('Selected project: ' + str(getattr(project, 'description', 'current checkout')))
            scope.setWordWrap(True)
            layout.addWidget(scope)
            button = QPushButton('Open project settings…')
            def open_project():
                from .settings_ui import SettingsDialog
                dialog = SettingsDialog(project, self)
                owner = self.parent()
                panel = owner if hasattr(owner, 'invalidate') else getattr(owner, 'panel', None)
                if dialog.exec() and panel is not None:
                    panel.invalidate()
                    panel.settings_saved.emit()
            button.clicked.connect(open_project)
            layout.addWidget(button)
        guide = QLabel('<b>Your next steps</b><br>1. Choose work and press Next to prepare a plan.'
                       '<br>2. Review the plan, then press Start to run tests.'
                       '<br>3. See Results and Timing. If delivery was selected, review the prepared files before approving it.'
                       '<br><br>Past runs opens saved results. Project settings configures the selected checkout. '
                       'The Setup menu manages accounts and test machines.')
        guide.setWordWrap(True)
        layout.addWidget(guide)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            save_profile(self.path, {'text_size': self.size.value()}, allowed={'text_size'})
            apply_preferences(QApplication.instance(), self.path)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.accept()
