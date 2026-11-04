"""Project bootstrap readiness independent of ordinary adapter/settings imports."""
from queue import Empty, Queue
from threading import Event
from PySide6.QtCore import QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .adapter_sdk import supports
from .redaction import Redactor
from .project_tooling import validate_status


class ToolingTask(QRunnable):
    def __init__(self, project, action, results):
        super().__init__()
        self.project, self.action, self.results = project, action, results
        self.cancelled, self.done = Event(), Event()

    def run(self):
        try:
            if self.cancelled.is_set():
                raise ValueError('Project tooling request cancelled.')
            value = (self.project.update_tooling(confirmed=True, cancelled=self.cancelled.is_set)
                     if self.action == 'update' else self.project.tooling_status(cancelled=self.cancelled.is_set))
            self.results.put((validate_status(value), None))
        except Exception as error:
            self.results.put((None, str(error)))
        finally:
            self.done.set()


class ProjectToolingDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.worker, self.last_status = project, None, None
        self.was_updated = False
        self.results = Queue()
        self.setWindowTitle('Project tooling')
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        self.message = QLabel('Checking project-owned tooling…')
        self.message.setTextFormat(Qt.TextFormat.PlainText); self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.revision = QLabel(); self.revision.setTextFormat(Qt.TextFormat.PlainText)
        self.revision.setWordWrap(True); layout.addWidget(self.revision)
        self.environments = QTreeWidget()
        self.environments.setHeaderLabels(['Environment', 'Readiness', 'Installed version'])
        layout.addWidget(self.environments)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        self.refresh = QPushButton('Check again'); self.refresh.clicked.connect(lambda: self.start('status'))
        self.update = QPushButton('Update project tooling…'); self.update.clicked.connect(self.confirm_update)
        self.close_button = QPushButton('Close'); self.close_button.clicked.connect(self.close)
        self.close_button.setDefault(True)
        for button in (self.refresh, self.update, self.close_button):
            button.setAutoDefault(False); buttons.addWidget(button)
        self.timer = QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.poll)
        self.start('status')

    def start(self, action):
        if self.worker is not None:
            return
        self.refresh.setEnabled(False); self.update.setEnabled(False)
        self.close_button.setEnabled(action != 'update')
        self.message.setText('Updating project-owned tooling…' if action == 'update' else 'Checking project-owned tooling…')
        self.worker = ToolingTask(self.project, action, self.results)
        self.timer.start(); QThreadPool.globalInstance().start(self.worker)

    def poll(self):
        try:
            value, error = self.results.get_nowait()
        except Empty:
            return
        updated = self.worker.action == 'update'
        self.worker = None; self.timer.stop()
        self.refresh.setEnabled(True); self.close_button.setEnabled(True)
        if error:
            self.last_status = None
            self.environments.clear(); self.revision.clear()
            self.message.setText(Redactor()(error))
            self.update.setEnabled(False)
            return
        self.last_status = value
        self.was_updated = self.was_updated or updated and value['ready']
        self.message.setText(Redactor()(value['message']))
        self.revision.setText('Project-declared version · ' + value['declared_revision'])
        self.environments.clear()
        for row in value['environments']:
            item = QTreeWidgetItem([row['name'], 'Ready' if row['ready'] else 'Needs attention', row['installed_revision'] or 'Not installed'])
            item.setToolTip(0, row['interpreter'])
            item.setToolTip(2, row['source_checkout'])
            self.environments.addTopLevelItem(item)
        self.update.setEnabled(value['status'] != 'blocked' and supports(self.project, 'tooling_update'))

    def confirm_update(self):
        if self.worker is not None or not self.last_status or self.last_status['status'] == 'blocked':
            return
        answer = QMessageBox.question(self, 'Update project tooling',
            'Update this project’s own environments to its declared dependency?\n\n'
            + self.last_status['declared_revision'] + '\n'
            + '\n'.join(row['name'] for row in self.last_status['environments']),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.start('update')

    def closeEvent(self, event):
        if self.worker is not None and self.worker.action == 'update' and not self.worker.done.is_set():
            self.message.setText('Project tooling update is still running. Wait for its result before closing.')
            event.ignore()
            return
        if self.worker is not None:
            self.worker.cancelled.set()
        self.timer.stop()
        super().closeEvent(event)
