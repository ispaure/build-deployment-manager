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
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QMenu, QToolButton, QGroupBox, QInputDialog)
from PySide6.QtCore import Qt, QTimer
from .bridge import ProjectBridge
from .ui import ManagerPanel
from .ui_components import style_button


_CURRENT_PROJECT = object()


class ManagerWindow(QWidget):
    def __init__(self,registry):
        super().__init__()
        from PySide6.QtCore import Qt
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.registry,self.panel,self.active = registry,None,False
        self.run_workspace = None
        self.run_number = 0
        self.close_pending = False
        self.setWindowTitle('Build Deployment Manager')
        self.resize(1200,850)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 8, 10, 8)
        self.layout.setSpacing(6)
        self.root_layout = self.layout
        self.documentation_window = None
        self.retired_panels = []
        from commonUtils.ui.workspaces.workspace import Workspace
        from commonUtils.ui.workspaces.workspace_policy import WorkspacePolicy
        self.run_workspace = Workspace(self.create_run, self,
            dock_group=f'build-manager-{id(self)}', keep_one_tab=True,
            policy=WorkspacePolicy(allow_last_tab_detach=False),
            new_view=self.new_run_tab, setup_container=self.connect_run_workspace)
        self.connect_run_workspace(self.run_workspace)
        self.root_layout.addWidget(self.run_workspace, 1)
        self.run_workspace.add_view(self.registry.read().get('selected') or '')

    def install_project_controls(self, view, key):
        view.project_key = key
        view.project_bar = QWidget()
        controls = view.controls = QHBoxLayout(view.project_bar)
        controls.setContentsMargins(0, 0, 0, 0)
        view.projects = QComboBox()
        view.projects.setMinimumContentsLength(18)
        view.projects.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        view.projects.setAccessibleName('Project for this run tab')
        controls.addWidget(view.projects, 1)
        view.project_settings = QPushButton('Project settings…')
        view.project_settings.clicked.connect(lambda: self.open_project_settings(view))
        controls.addWidget(view.project_settings)
        view.more = QToolButton()
        view.more.setText('More')
        view.more.setAccessibleName('Project, setup and application menu for this tab')
        menu = QMenu(view.more)
        view.menu_actions = {}
        for group in (
                [('Add project…', lambda: self.add(view)), ('Locate moved checkout…', lambda: self.locate(view)),
                 ('Remove registration', lambda: self.remove(view))],
                [('Accounts…', lambda: self.accounts(view)), ('Test machines…', lambda: self.test_machines(view)),
                 ('Check connections and settings…', lambda: view.verify_settings() if view.project else None),
                 ('Clean up builds…', lambda: view.clean_builds() if view.project and hasattr(view.project, 'storage_inventory') else None)],
                [('App settings…', lambda: self.open_app_settings(view))]):
            if view.menu_actions:
                menu.addSeparator()
            for label, action in group:
                view.menu_actions[label] = menu.addAction(label, action)
        view.more.setMenu(menu)
        view.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        controls.addWidget(view.more)
        view.help_button = QToolButton()
        view.help_button.setText('?')
        view.help_button.setAccessibleName('Build Deployment Manager documentation')
        view.help_button.setToolTip('Open user and developer documentation')
        view.help_button.clicked.connect(self.open_documentation)
        controls.addWidget(view.help_button)
        view.layout().insertWidget(0, view.project_bar)
        view.setup_card = QGroupBox('Project setup')
        setup = QHBoxLayout(view.setup_card)
        view.setup_summary = QLabel()
        view.setup_summary.setWordWrap(True)
        setup.addWidget(view.setup_summary, 1)
        view.setup_action = style_button(QPushButton('Add your first project…'), 'primary')
        view.setup_action.clicked.connect(lambda: self.next_setup_step(view))
        setup.addWidget(view.setup_action)
        view.layout().insertWidget(1, view.setup_card)
        view.projects.currentIndexChanged.connect(lambda *_: self.select(view))
        self.refresh_picker(view)
        self.update_setup(view)
        self.update_project_actions(view)

    def refresh_picker(self, view):
        data = self.registry.read()
        picker = view.projects
        picker.blockSignals(True)
        picker.clear()
        names = [row['name'] for row in data['projects'].values()]
        for key, row in data['projects'].items():
            label = row['name'] + (' · ' + row['root'] if names.count(row['name']) > 1 else '')
            picker.addItem(label, key)
            picker.setItemData(picker.count() - 1, row['root'], Qt.ItemDataRole.ToolTipRole)
        if view.project_key and view.project_key not in data['projects']:
            picker.addItem(view.project_key + ' · not registered', view.project_key)
        picker.setCurrentIndex(picker.findData(view.project_key))
        picker.blockSignals(False)
        picker.setToolTip(picker.itemData(picker.currentIndex(), Qt.ItemDataRole.ToolTipRole) or '')

    def new_run_tab(self, workspace):
        source = workspace.active_view
        key = source.project_key if source is not None else self.registry.read().get('selected')
        return workspace.add_view(key or '')

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

    def open_app_settings(self, view=None):
        from .application_settings_ui import ApplicationSettingsDialog
        view = view or self.current_view
        ApplicationSettingsDialog(view.project, view.window(),
            directory=getattr(self.registry, 'directory', None)).exec()

    def open_project_settings(self, view=None):
        view = view or self.current_view
        if view.project is not None:
            view.edit_settings()

    def guarded(self, action, view=None):
        try:
            return action()
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            self.show_status(str(error), view)

    def show_status(self, text, view=None):
        view = view or self.current_view
        view.status.setText(view.redact(text) if hasattr(view, 'redact') else text)
        view.status.show()

    def refresh(self, *, view=None, selected=_CURRENT_PROJECT, force=False):
        for dock in self.run_workspace.all_docks:
            self.refresh_picker(dock.widget())
        if view is not None:
            self.select(view, selected=selected, force=force)
        else:
            self.update_setup(self.current_view)

    def select(self, view=None, *, selected=_CURRENT_PROJECT, force=False):
        view = view or self.current_view
        key = view.projects.currentData() if selected is _CURRENT_PROJECT else selected
        if getattr(view, 'is_busy', False):
            self.refresh_picker(view)
            return
        if key == view.project_key and not force:
            return
        try:
            replacement = self.create_run(key, run_number=view.run_number)
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            self.refresh_picker(view)
            self.show_status('Could not open project: ' + str(error), view)
            return
        dock = next((dock for dock in self.run_workspace.all_docks if dock.widget() is view), None)
        if dock is None:
            replacement.close()
            replacement.deleteLater()
            return
        # Retire only this idle view. The existing dock retains its position,
        # detached window and sibling tabs; its replacement owns a fresh session.
        if hasattr(view, 'idle'):
            view.idle.disconnect()
            view.idle.connect(lambda: self.close() if self.close_pending else None)
        view.hide()
        dock.setWidget(replacement)
        view.setParent(self)
        view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.retired_panels.append(view)
        view.destroyed.connect(lambda: self.retired_panels.remove(view) if view in self.retired_panels else None)
        view.close()
        replacement.setProperty('workspaceView', True)
        replacement.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if hasattr(replacement, 'idle'):
            replacement.idle.connect(lambda: dock.workspace._retry_view_close(dock))
        dock.setWindowTitle(replacement.view_title)
        replacement.show()
        self.activate_run(replacement)
        if key:
            self.guarded(lambda: self.registry.select(key), replacement)
        self.set_active(False)

    def connect_run_workspace(self, workspace):
        workspace.active_changed.connect(self.activate_run)
        workspace.tabs_changed.connect(self.run_tabs_changed)

    def run_tabs_changed(self):
        docks = self.run_workspace.all_docks if self.run_workspace else []
        if docks and getattr(self, 'current_view', None) not in [dock.widget() for dock in docks]:
            dock = self.run_workspace.active_dock
            self.activate_run((dock if dock in docks else docks[0]).widget())
        self.set_active(False)

    def create_run(self, key=None, *, run_number=None):
        if key is None and run_number is None and self.panel is not None:
            key = self.panel.project_key
        key = key or None
        replacing = run_number is not None
        if run_number is None:
            self.run_number += 1
            run_number = self.run_number
        project, load_error = None, ''
        if key:
            try:
                project = ProjectBridge(self.registry, key)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                if replacing:
                    raise
                load_error = str(error)
        if project is not None:
            panel = ManagerPanel(project, self)
            panel.app_settings.hide()
            panel.identity.hide()
            panel.settings.hide()
            panel.applying_preset = True
            try:
                panel.configuration.restore_choices(project.row.get('selections', {}))
            finally:
                panel.applying_preset = False
            panel.selection_changed.connect(lambda choices: self.guarded(
                lambda: self.registry.selections(key, choices), panel))
            self.install_presets(key, panel)
            panel.busy_changed.connect(self.set_active)
            panel.history_in_tabs = True
            panel.retained_run_requested.connect(lambda item: self.open_retained_run(item, panel))
            panel.idle.connect(lambda: self.close() if self.close_pending else None)
            panel.settings_saved.connect(lambda: self.project_settings_saved(panel))
        else:
            panel = QWidget(self)
            QVBoxLayout(panel)
            panel.project = None
            panel.project_error = load_error
            panel.prepare_close = lambda: True
            panel.status = QLabel('')
            panel.status.setWordWrap(True)
            panel.layout().addWidget(panel.status)
            empty = QLabel('Add a local project folder, choose your work, then review its plan before starting.')
            empty.setWordWrap(True)
            panel.layout().addWidget(empty)
            panel.layout().addStretch()
        panel.run_number = run_number
        name = self.registry.read()['projects'].get(key, {}).get('name', 'New project')
        panel.view_title = f'{name} · Run {run_number}'
        self.install_project_controls(panel, key)
        return panel

    def open_retained_run(self, item, source=None):
        source = source or self.panel
        dock = next((dock for dock in self.run_workspace.all_docks if dock.widget() is source), None)
        workspace = dock.workspace if dock is not None else self.run_workspace
        panel = workspace.add_view(source.project_key)
        if panel is not None:
            panel.open_history(item, in_tab=True)

    def activate_run(self, view):
        if view is None:
            return
        self.current_view = view
        self.panel = view if view.project is not None else None
        for name in ('controls', 'projects', 'project_settings', 'more', 'menu_actions', 'help_button',
                     'setup_card', 'setup_summary', 'setup_action', 'status'):
            setattr(self, name, getattr(view, name))
        self.buttons = [view.project_settings, view.more]
        self.add_project = view.menu_actions['Add project…']
        self.app_settings = view.menu_actions['App settings…']
        if self.panel is not None:
            view.refresh_saved_presets()
            self.saved_presets = view.saved_presets
            self.preset_actions = view.preset_actions
            self.preset_menu = view.preset_menu
        self.set_active(False)

    def install_presets(self, key, panel):
        from .presets_ui import PresetController
        panel.preset_controller = PresetController(self.registry, key, panel, self.guarded)

    def project_settings_saved(self, origin):
        for dock in self.run_workspace.all_docks:
            view = dock.widget()
            if view is not origin and view.project_key == origin.project_key and view.project is not None:
                view.invalidate()
        self.show_status('Project settings saved. Review a fresh plan before running.', origin)

    def update_setup(self, view=None):
        view = view or self.current_view
        view.setup_card.hide()
        if view.project is None:
            view.setup_card.show()
            error = getattr(view, 'project_error', '')
            view.setup_summary.setText('Could not open this project: ' + error if error else
                'Add a project to this run tab. Other tabs keep their own project and choices.')
            view.setup_action.setText('Locate moved checkout…' if error else 'Add your first project…')
            return
        from .project_setup_ui import interpreter_path
        row, descriptor = self.registry.resolve(view.project_key)
        python = interpreter_path(row['root'], descriptor)
        if not python.is_file():
            view.setup_card.show()
            view.setup_summary.setText('Environment missing · This project needs its own Python environment before settings and plans can load.\n' + str(python))
            view.setup_action.setText('View setup instructions…')

    def next_setup_step(self, view=None):
        view = view or self.current_view
        if view.project is None:
            self.locate(view) if view.project_key else self.add(view)
            return
        from .project_setup_ui import interpreter_path
        row, descriptor = self.registry.resolve(view.project_key)
        python = interpreter_path(row['root'], descriptor)
        if not python.is_file():
            QMessageBox.information(view.window(), 'Set up this project’s environment',
                f"Project: {descriptor['name']}\nFolder: {row['root']}\nExpected Python: {python}\n\n"
                'Follow this project’s installation guide to create its environment. '
                'Keep its dependencies separate from the manager. Then open Project settings again.')
        else:
            view.edit_settings()

    def update_project_actions(self, view):
        busy = getattr(view, 'is_busy', False)
        available = bool(view.project_key)
        view.projects.setEnabled(not busy)
        view.more.setEnabled(not busy)
        view.setup_action.setEnabled(not busy)
        view.project_settings.setEnabled(not busy and view.project is not None)
        for label in ('Locate moved checkout…', 'Remove registration', 'Accounts…', 'Check connections and settings…'):
            view.menu_actions[label].setEnabled(available and not busy)
        view.menu_actions['Clean up builds…'].setEnabled(not busy and view.project is not None and hasattr(view.project, 'storage_inventory'))

    def set_active(self, value):
        docks = self.run_workspace.all_docks if self.run_workspace else []
        self.active = any(getattr(dock.widget(), 'is_busy', False) for dock in docks)
        for dock in docks:
            self.update_project_actions(dock.widget())

    def add(self, view=None):
        view = view or self.current_view
        from .project_setup_ui import AddProjectDialog
        dialog = AddProjectDialog(view.window())
        if dialog.exec():
            def register():
                key = self.registry.add(dialog.root)
                self.registry.select(key)
                self.refresh(view=view, selected=key)
            self.guarded(register, view)

    def locate(self, view=None):
        view = view or self.current_view
        path = QFileDialog.getExistingDirectory(view.window(), 'Locate moved project checkout')
        if path:
            def relocate():
                self.registry.locate(view.project_key, path)
                self.refresh(view=view, selected=view.project_key, force=True)
            self.guarded(relocate, view)

    def accounts(self, view=None):
        view = view or self.current_view
        from .accounts_ui import AccountsDialog
        from .settings import SettingsStore
        key = view.project_key
        def show():
            row, descriptor = self.registry.resolve(key)
            if AccountsDialog(SettingsStore(self.registry.directory), descriptor['project_id'], view.window(),
                    providers=descriptor['capabilities'].get('providers', ())).exec():
                if view.project:
                    view.invalidate()
        if key:
            self.guarded(show, view)

    def remove(self, view=None):
        view = view or self.current_view
        key = view.project_key
        if any(dock.widget().project_key == key and getattr(dock.widget(), 'is_busy', False) for dock in self.run_workspace.all_docks):
            self.show_status('This project is running in another tab. Wait before removing its registration.', view)
            return
        if key and QMessageBox.question(view.window(), 'Remove project from this list?',
                'The project folder, settings and saved results will be kept. You can add it again later.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            def remove():
                self.registry.remove(key)
                self.refresh(view=view, selected=self.registry.read().get('selected'))
            self.guarded(remove, view)

    def test_machines(self, view=None):
        view = view or self.current_view
        from .vm_ui import VMDialog
        VMDialog(view.window()).exec()

    def closeEvent(self,event):
        busy_panels = [dock.widget() for dock in self.run_workspace.all_docks
                       if getattr(dock.widget(), 'is_busy', False)] if self.run_workspace else []
        if busy_panels:
            if QMessageBox.question(self,'Cancel active operations?',
                'Cancel and finish owned cleanup before closing?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                for panel in busy_panels:
                    panel.cancel_operation()
                    panel.busy_changed.connect(lambda busy: self.close() if not self.active else None)
            event.ignore()
            return
        if self.retired_panels:
            self.close_pending = True
            if not all(panel.prepare_close() for panel in tuple(self.retired_panels)):
                event.ignore()
                return
        if self.run_workspace is not None:
            self.close_pending = True
            if not self.run_workspace.prepare_close():
                event.ignore()
                return
            for window in tuple(self.run_workspace.detached_windows):
                for dock in tuple(window.workspace.docks):
                    dock.close()
                window.close()
        event.accept()
