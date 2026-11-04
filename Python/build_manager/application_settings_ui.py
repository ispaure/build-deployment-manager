"""Application preferences, distinct from project-owned settings."""
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout)
from .profiles import load_profile, save_profile
from .ui_components import style_dialog_buttons, install_font_refresh, style_utilities
from .registry import config_directory


def preferences_path(project=None):
    registry = getattr(project, 'registry', None)
    return Path(getattr(registry, 'directory', config_directory())) / 'appearance.json'


def apply_preferences(app, path):
    from .palette_ui import install_palette_refresh
    install_palette_refresh(app)
    install_font_refresh(app)
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
        self.resize(540, 300)
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
        folder = self.path.parent / 'configuration'
        open_folder = QPushButton('Open configuration folder')
        open_folder.setToolTip(str(folder))
        def show_folder():
            from .configuration_files import ensure_configuration
            try:
                ensure_configuration(self.path.parent)
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
                    self.status.setText('Configuration folder: ' + str(folder))
            except (OSError, ValueError, RuntimeError) as error:
                self.status.setText(str(error))
        open_folder.clicked.connect(show_folder)
        layout.addStretch()
        layout.addWidget(open_folder)
        self.preview = QLabel('Build Deployment Manager · source, checks and delivery')
        self.preview.setWordWrap(True)
        self.preview.setAccessibleName('Text size preview')
        def preview_size():
            font = QFont(getattr(QApplication.instance(), '_manager_default_font', QApplication.font()))
            if self.size.value():
                font.setPointSize(self.size.value())
            self.preview.setFont(font)
        self.size.valueChanged.connect(preview_size)
        preview_size()
        layout.insertWidget(2, self.preview)
        reset = QPushButton('Use system text size')
        reset.clicked.connect(lambda: self.size.setValue(0))
        layout.insertWidget(3, reset)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        style_dialog_buttons(buttons)
        layout.addWidget(buttons)
        style_utilities(self)

    def save(self):
        try:
            save_profile(self.path, {'text_size': self.size.value()}, allowed={'text_size'})
            apply_preferences(QApplication.instance(), self.path)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.accept()
