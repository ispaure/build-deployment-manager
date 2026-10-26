"""Standalone project selector; trusted adapters remain in separate processes."""
import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-exit', action='store_true', help='Start and cleanly close the empty GUI for local acceptance')
    parser.add_argument('--registry', type=Path)
    args = parser.parse_args(argv)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    app = QApplication.instance() or QApplication([])
    from .registry import Registry
    from .application_settings_ui import apply_preferences
    from .registry import config_directory
    try:
        apply_preferences(app, (args.registry or config_directory()) / 'appearance.json')
    except (OSError, ValueError):
        pass
    window = ManagerWindow(Registry(args.registry))
    window.show()
    if args.smoke_exit:
        QTimer.singleShot(150,window.close)
    return app.exec()


# Qt imports are isolated in this GUI-only module.
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QMenu, QToolButton, QGroupBox, QScrollArea, QFrame, QInputDialog)
from .bridge import ProjectBridge
from .ui import ManagerPanel


class ManagerWindow(QWidget):
    def __init__(self,registry):
        super().__init__()
        from PySide6.QtCore import Qt
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.registry,self.panel,self.active = registry,None,False
        self.setWindowTitle('Build Deployment Manager')
        self.resize(1200,850)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 8)
        self.layout.setSpacing(6)
        self.controls = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setAccessibleName('Selected project checkout')
        self.controls.addWidget(self.projects,1)
        self.buttons = []
        self.add_project = QPushButton('Add project…')
        self.add_project.clicked.connect(self.add)
        self.controls.addWidget(self.add_project)
        self.buttons.append(self.add_project)
        self.project_settings = QPushButton('Project settings…')
        self.project_settings.clicked.connect(self.open_project_settings)
        self.controls.addWidget(self.project_settings)
        self.buttons.append(self.project_settings)
        self.menu_actions = {}
        for title, actions in (
                ('Project', [('Locate moved checkout…', self.locate),
                             ('Remove registration', self.remove)]),
                ('Setup', [('Accounts…', self.accounts), ('Test machines…', self.test_machines),
                           ('Check connections and settings…', lambda: self.panel.verify_settings() if self.panel else None),
                           ('Clean up builds…', lambda: self.panel.clean_builds() if self.panel and hasattr(self.panel.project, 'storage_inventory') else None)])):
            button = QToolButton()
            button.setText(title)
            button.setAccessibleName(title + ' menu')
            menu = QMenu(button)
            for label, action in actions:
                self.menu_actions[label] = menu.addAction(label, action)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.controls.addWidget(button)
            self.buttons.append(button)
        self.app_settings = QPushButton('App settings…')
        self.app_settings.clicked.connect(self.open_app_settings)
        self.controls.addWidget(self.app_settings)
        self.buttons.append(self.app_settings)
        self.documentation_window = None
        self.help_button = QToolButton()
        self.help_button.setText('?')
        self.help_button.setAccessibleName('Build Deployment Manager documentation')
        self.help_button.setToolTip('Open user and developer documentation')
        self.help_button.clicked.connect(self.open_documentation)
        self.controls.addWidget(self.help_button)
        self.layout.addLayout(self.controls)
        self.status=QLabel('Add a project checkout to load its settings and prepare work.')
        self.status.setWordWrap(True);self.layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.scroll.setWidget(content)
        self.layout.addWidget(self.scroll,1)
        self.root_layout = self.layout
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)
        self.setup_card = QGroupBox('Project setup')
        setup_layout = QHBoxLayout(self.setup_card)
        self.setup_summary = QLabel()
        self.setup_summary.setWordWrap(True)
        setup_layout.addWidget(self.setup_summary, 1)
        self.setup_action = QPushButton('Add your first project…')
        self.setup_action.clicked.connect(self.next_setup_step)
        setup_layout.addWidget(self.setup_action)
        self.layout.addWidget(self.setup_card)
        self.empty = QLabel('1. Add a local project folder.\n\n'
            '2. Check its tools and destinations in Project settings.\n\n'
            '3. Choose what to test, review the plan, then press Start.\n\n'
            'Past runs keeps results separate from your next run.')
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty.setMargin(20)
        self.layout.addWidget(self.empty, 1)
        self.projects.currentIndexChanged.connect(self.select)
        self.refresh()

    def open_documentation(self):
        from commonUtils.ui.document_host import show_document
        from commonUtils.ui.markdown import open_markdown
        if self.documentation_window is None:
            directory = Path(__file__).resolve().parents[2] / 'docs'
            self.documentation_window = open_markdown(directory / 'docs.md', parent=self,
                                                       directory=directory)
            self.documentation_window.destroyed.connect(
                lambda: setattr(self, 'documentation_window', None))
        else:
            show_document(self.documentation_window)

    def open_app_settings(self):
        from .application_settings_ui import ApplicationSettingsDialog
        ApplicationSettingsDialog(self.panel.project if self.panel else None, self,
            directory=getattr(self.registry, 'directory', None)).exec()

    def open_project_settings(self):
        if self.panel is not None:
            self.panel.edit_settings()

    def guarded(self,action):
        try:
            action()
        except (OSError,ValueError,RuntimeError,KeyError) as error:
            self.status.setText(str(error))

    def refresh(self):
        data=self.registry.read();self.projects.blockSignals(True);self.projects.clear()
        for key,row in data['projects'].items():
            self.projects.addItem(row['name']+' · '+row['root'],key)
        self.projects.setCurrentIndex(self.projects.findData(data.get('selected')))
        self.projects.blockSignals(False);self.select()

    def select(self,*_):
        if self.active:
            return
        key=self.projects.currentData()
        self.empty.setVisible(not bool(key))
        self.project_settings.setEnabled(bool(key))
        self.setup_card.hide()
        if not key:
            self.setup_summary.setText('Start by adding a project. Its source files and existing settings stay in their project folder.')
            self.setup_action.setText('Add your first project…')
        for label in ('Locate moved checkout…', 'Remove registration',
                      'Accounts…', 'Check connections and settings…', 'Clean up builds…'):
            self.menu_actions[label].setEnabled(bool(key))
        if self.panel:
            if not self.panel.close():
                return
            self.layout.removeWidget(self.panel);self.panel.hide();self.panel.deleteLater();self.panel=None
        if key:
            def change():
                self.registry.select(key)
                project=ProjectBridge(self.registry,key)
                self.panel=ManagerPanel(project,self)
                self.panel.app_settings.hide()
                self.panel.identity.hide()
                self.panel.settings.hide()
                self.menu_actions['Clean up builds…'].setEnabled(hasattr(project, 'storage_inventory'))
                self.panel.applying_preset = True
                try:
                    self.panel.configuration.restore_choices(project.row.get('selections', {}))
                finally:
                    self.panel.applying_preset = False
                self.panel.selection_changed.connect(lambda choices: self.guarded(
                    lambda: self.registry.selections(key, choices)))
                self.install_presets(key)
                self.panel.busy_changed.connect(self.set_active)
                self.panel.settings_saved.connect(lambda: self.status.setText('Project settings saved. Review a fresh plan before running.'))
                self.layout.addWidget(self.panel)
                self.update_setup()
            self.guarded(change)

    def install_presets(self, key):
        panel = self.panel
        row = QHBoxLayout()
        self.saved_presets = QComboBox()
        self.saved_presets.setAccessibleName('Saved project run presets')
        self.saved_presets.setToolTip('Private presets for this project checkout. Loading only changes choices; review before running.')
        self.saved_presets.addItem('Saved run presets…', None)
        for name in self.registry.read()['projects'][key].get('presets', {}):
            self.saved_presets.addItem(name, name)
        row.addWidget(self.saved_presets, 1)
        load = QPushButton('Load preset')
        save = QPushButton('Save preset…')
        delete = QPushButton('Delete preset')
        for button in (load, save, delete):
            row.addWidget(button)
            panel.busy_changed.connect(lambda busy, control=button: control.setEnabled(not busy))
        panel.busy_changed.connect(lambda busy: self.saved_presets.setEnabled(not busy))
        panel.layout().insertLayout(1, row)
        def load_selected():
            name = self.saved_presets.currentData()
            if name is None:
                return
            choices = self.registry.read()['projects'][key]['presets'][name]
            panel.applying_preset = True
            try:
                panel.configuration.restore_choices(choices)
            finally:
                panel.applying_preset = False
            panel.invalidate()
            panel.stages.setCurrentIndex(0)
            panel.status.setText('Loaded preset: ' + name + '. Review the plan before running.')
        def save_selected():
            if panel.run_fields.timer.isActive():
                raise ValueError('Project defaults are still loading. Save the preset once they have loaded.')
            name, accepted = QInputDialog.getText(self, 'Save run preset',
                'Preset name (an existing name replaces that preset):', text=self.saved_presets.currentData() or '')
            if not accepted:
                return
            choices = panel.choices()
            # Capture current field values, including project defaults, in a named preset.
            from PySide6.QtWidgets import QPlainTextEdit
            choices['run_overrides'] = {name: field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()
                                       for name, field in panel.run_fields.controls.items()}
            self.registry.save_preset(key, name, choices)
            name = name.strip()
            if self.saved_presets.findData(name) < 0:
                self.saved_presets.addItem(name, name)
            self.saved_presets.setCurrentIndex(self.saved_presets.findData(name))
            panel.status.setText('Saved private run preset: ' + name)
        def delete_selected():
            name = self.saved_presets.currentData()
            if name is not None:
                self.registry.delete_preset(key, name)
                self.saved_presets.removeItem(self.saved_presets.currentIndex())
        load.clicked.connect(lambda: self.guarded(load_selected))
        save.clicked.connect(lambda: self.guarded(save_selected))
        delete.clicked.connect(lambda: self.guarded(delete_selected))

    def update_setup(self):
        if self.panel is None:
            return
        from .project_setup_ui import interpreter_path
        row, descriptor = self.registry.resolve(self.projects.currentData())
        python = interpreter_path(row['root'], descriptor)
        if not python.is_file():
            self.setup_card.show()
            self.setup_summary.setText('Environment missing · This project needs its own Python environment before settings and plans can load.\n' + str(python))
            self.setup_action.setText('View setup instructions…')
        else:
            self.setup_card.hide()
            self.setup_summary.setText('Project added · Check tools and destinations in Project settings, then choose your work below.')
            self.setup_action.setText('Project settings…')
        self.status.setText('Selected project: ' + descriptor['name'])

    def next_setup_step(self):
        if self.panel is None:
            self.add()
            return
        from .project_setup_ui import interpreter_path
        row, descriptor = self.registry.resolve(self.projects.currentData())
        python = interpreter_path(row['root'], descriptor)
        if not python.is_file():
            QMessageBox.information(self, 'Set up this project’s environment',
                f"Project: {descriptor['name']}\nFolder: {row['root']}\nExpected Python: {python}\n\n"
                'Follow this project’s installation guide to create its environment. '
                'Keep its dependencies separate from the manager. Then open Project settings again.')
        else:
            self.panel.edit_settings()

    def set_active(self,value):
        self.active=value;self.projects.setEnabled(not value)
        for button in self.buttons:button.setEnabled(not value)
        self.setup_action.setEnabled(not value)

    def add(self):
        from .project_setup_ui import AddProjectDialog
        dialog = AddProjectDialog(self)
        if dialog.exec():
            def register():
                key = self.registry.add(dialog.root)
                self.registry.select(key)
                self.refresh()
            self.guarded(register)

    def locate(self):
        path=QFileDialog.getExistingDirectory(self,'Locate moved project checkout')
        if path:self.guarded(lambda:self.registry.locate(self.projects.currentData(),path));self.refresh()

    def accounts(self):
        from .accounts_ui import AccountsDialog
        from .settings import SettingsStore
        key=self.projects.currentData()
        def show():
            row,descriptor=self.registry.resolve(key)
            if AccountsDialog(SettingsStore(self.registry.directory),descriptor['project_id'],self,
                    providers=descriptor['capabilities'].get('providers',())).exec():
                if self.panel:self.panel.invalidate()
        if key:self.guarded(show)

    def remove(self):
        key=self.projects.currentData()
        if key and QMessageBox.question(self, 'Remove project from this list?',
                'The project folder, settings and saved results will be kept. You can add it again later.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.guarded(lambda:self.registry.remove(key));self.refresh()

    def test_machines(self):
        from .vm_ui import VMDialog
        VMDialog(self).exec()

    def closeEvent(self,event):
        if self.active:
            if QMessageBox.question(self,'Cancel active operation?',
                'Cancel and finish owned cleanup before closing?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.panel.cancel_operation()
                self.panel.busy_changed.connect(lambda busy:self.close() if not busy else None)
            event.ignore();return
        if self.panel is not None and not self.panel.close():
            event.ignore()
            return
        event.accept()
