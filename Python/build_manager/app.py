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
    window = ManagerWindow(Registry(args.registry))
    window.show()
    if args.smoke_exit:
        QTimer.singleShot(150,window.close)
    return app.exec()


# Qt imports are isolated in this GUI-only module.
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget)
from .bridge import ProjectBridge
from .ui import ManagerPanel


class ManagerWindow(QWidget):
    def __init__(self,registry):
        super().__init__()
        self.registry,self.panel,self.active = registry,None,False
        self.setWindowTitle('Build Deployment Manager')
        self.resize(1200,850)
        self.layout = QVBoxLayout(self)
        self.controls = QHBoxLayout()
        self.projects = QComboBox()
        self.projects.setAccessibleName('Selected project checkout')
        self.controls.addWidget(self.projects,1)
        self.buttons = []
        for label,action in [('Add project',self.add),('Locate moved checkout',self.locate),
                              ('Trust adapter',self.trust),('Accounts',self.accounts),('Remove registration',self.remove)]:
            button=QPushButton(label);button.clicked.connect(action)
            self.controls.addWidget(button);self.buttons.append(button)
        self.layout.addLayout(self.controls)
        self.status=QLabel('Add a project descriptor, review it, then trust its adapter before executing project code.')
        self.status.setWordWrap(True);self.layout.addWidget(self.status)
        self.projects.currentIndexChanged.connect(self.select)
        self.refresh()

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
        if self.panel:
            self.layout.removeWidget(self.panel);self.panel.deleteLater();self.panel=None
        if key:
            def change():
                self.registry.select(key)
                project=ProjectBridge(self.registry,key)
                self.panel=ManagerPanel(project,self)
                for name,value in project.row.get('selections', {}).items():
                    control=getattr(self.panel,name)
                    if name == 'suite':control.setCurrentIndex(max(0,control.findData(value)))
                    elif name in ('operation','platform','backend'):control.setCurrentText(value)
                    else:control.setText(value)
                self.panel.selection_changed.connect(lambda choices:self.registry.selections(key,choices))
                self.panel.busy_changed.connect(self.set_active)
                self.layout.addWidget(self.panel)
                self.status.setText(project.description+' · '+('trusted' if project.row['trusted'] else 'review and trust required'))
            self.guarded(change)

    def set_active(self,value):
        self.active=value;self.projects.setEnabled(not value)
        for button in self.buttons:button.setEnabled(not value)

    def add(self):
        path=QFileDialog.getExistingDirectory(self,'Select a checkout with build-project.json')
        if path:self.guarded(lambda:self.registry.add(path));self.refresh()

    def locate(self):
        path=QFileDialog.getExistingDirectory(self,'Locate moved project checkout')
        if path:self.guarded(lambda:self.registry.locate(self.projects.currentData(),path));self.refresh()

    def trust(self):
        import json
        key=self.projects.currentData()
        if not key:return
        def review():
            row,descriptor=self.registry.resolve(key)
            if QMessageBox.question(self,'Trust local adapter code?',
                'This runs project-owned code in its declared interpreter. Review the checkout first.\n\n'+json.dumps(descriptor,indent=2),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.registry.trust(key);self.refresh()
        self.guarded(review)

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
        if key:self.guarded(lambda:self.registry.remove(key));self.refresh()

    def closeEvent(self,event):
        if self.active:
            if QMessageBox.question(self,'Cancel active operation?',
                'Cancel and finish owned cleanup before closing?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.panel.cancel_operation()
                self.panel.busy_changed.connect(lambda busy:self.close() if not busy else None)
            event.ignore();return
        event.accept()
