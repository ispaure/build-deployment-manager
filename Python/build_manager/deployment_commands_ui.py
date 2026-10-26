"""Optional Qt controls for project-supplied interactive deployment commands."""
import codecs
from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


@dataclass(frozen=True)
class CommandAction:
    key: str
    label: str
    inventory: bool = False
    tooltip: str = ''


@dataclass(frozen=True)
class CommandTarget:
    label: str
    value: object


@dataclass(frozen=True)
class CommandInventory:
    targets: tuple[CommandTarget, ...]
    summary: str
    errors: tuple[str, ...] = ()


class CommandPanel(QWidget):
    """Policy supplies actions, command(action, target), inventory(text), logs(action).

    Policy also supplies confirmation_marker, confirmation_title and hint. No
    device discovery, signing, provider, module name or interpreter is inferred.
    """
    busy_changed = Signal(bool)

    def __init__(self, policy, parent=None):
        super().__init__(parent)
        self.policy = policy
        self.busy = self.external_busy = False
        self.mode = ''
        self.action_specs = {action.key: action for action in policy.actions}
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        layout = QVBoxLayout(self)
        self.devices = QLabel('Checking devices…')
        self.devices.setWordWrap(True)
        layout.addWidget(self.devices)
        row = QHBoxLayout()
        row.addWidget(QLabel('Deploy to:'))
        self.target = QComboBox()
        self.target.addItem('All available devices', None)
        row.addWidget(self.target, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.actions = {}
        for action in policy.actions:
            button = QPushButton(action.label)
            button.setToolTip(action.tooltip)
            button.clicked.connect(lambda checked=False, key=action.key: self.start(key))
            self.actions[action.key] = button
            row.addWidget(button)
        layout.addLayout(row)
        hint = QLabel(policy.hint)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(6000)
        layout.addWidget(self.output)
        row = QHBoxLayout()
        self.status = QLabel('Ready')
        row.addWidget(self.status, 1)
        logs = QPushButton('Open logs')
        logs.clicked.connect(self.open_logs)
        row.addWidget(logs)
        layout.addLayout(row)

    def open_logs(self):
        path = Path(self.policy.logs(self.mode))
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh_labels(self):
        for action in self.policy.actions:
            self.actions[action.key].setText(action.label)

    def set_external_busy(self, busy):
        self.external_busy = busy
        self.update_controls()

    def set_busy(self, busy):
        self.busy = busy
        self.update_controls()
        self.busy_changed.emit(busy)

    def update_controls(self):
        enabled = not (self.busy or self.external_busy)
        self.target.setEnabled(enabled)
        for button in self.actions.values():
            button.setEnabled(enabled)

    def start(self, key):
        if self.busy or self.external_busy:
            return
        action = self.action_specs[key]
        self.mode = key
        self.pending = self.raw_output = ''
        self.protocol_failed = False
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.error_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        if not action.inventory:
            self.output.clear()
        try:
            command = self.policy.command(key, self.target.currentData())
            environment = QProcessEnvironment.systemEnvironment()
            for name, value in (command.environment or {}).items():
                environment.insert(name, value)
            self.process.setWorkingDirectory(command.cwd)
            self.process.setProcessEnvironment(environment)
            self.set_busy(True)
            self.status.setText('Checking devices…' if action.inventory else 'Running…')
            self.process.start(command.argv[0], list(command.argv[1:]))
        except (OSError, ValueError, RuntimeError) as error:
            self.append(str(error) + '\n')
            self.status.setText('Failed — see output and logs')
            self.set_busy(False)

    def update_targets(self, targets):
        previous = self.target.currentData()
        previous_label = self.target.currentData(Qt.ItemDataRole.UserRole + 1) or self.target.currentText()
        self.target.clear()
        self.target.addItem('All available devices', None)
        for target in targets:
            self.target.addItem(target.label, target.value)
            self.target.setItemData(self.target.count() - 1, target.label, Qt.ItemDataRole.UserRole + 1)
        if previous is not None:
            index = next((i for i in range(1, self.target.count()) if self.target.itemData(i) == previous), -1)
            if index < 0:
                self.target.addItem(previous_label + ' (unavailable)', previous)
                index = self.target.count() - 1
                self.target.setItemData(index, previous_label, Qt.ItemDataRole.UserRole + 1)
            self.target.setCurrentIndex(index)

    def append(self, text):
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text)
        self.output.ensureCursorVisible()

    def read_stdout(self):
        self.consume_stdout(self.decoder.decode(bytes(self.process.readAllStandardOutput())))

    def consume_stdout(self, text):
        if self.action_specs[self.mode].inventory:
            self.raw_output += text
            return
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            self.consume_line(line)

    def consume_line(self, line):
        marker = self.policy.confirmation_marker
        if not marker or not line.startswith(marker):
            self.append(line + '\n')
            return
        try:
            prompt = json.loads(line[len(marker):])
            if not isinstance(prompt, str):
                raise ValueError('Confirmation prompt must be text.')
        except ValueError:
            self.protocol_failed = True
            self.append('Invalid confirmation request; declined.\n')
            self.process.write(b'n\n')
            return
        answer = QMessageBox.question(self, self.policy.confirmation_title, prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        self.process.write(b'y\n' if answer == QMessageBox.StandardButton.Yes else b'n\n')

    def read_stderr(self):
        self.append(self.error_decoder.decode(bytes(self.process.readAllStandardError())))

    def finished(self, code, exit_status):
        self.read_stdout()
        self.read_stderr()
        self.consume_stdout(self.decoder.decode(b'', final=True))
        self.append(self.error_decoder.decode(b'', final=True))
        # A final unterminated line is output, never an actionable upload prompt.
        self.append(self.pending)
        ok = code == 0 and exit_status == QProcess.ExitStatus.NormalExit and not self.protocol_failed
        inventory = self.action_specs[self.mode].inventory
        if inventory and ok:
            try:
                result = self.policy.inventory(self.raw_output)
                self.update_targets(result.targets)
                self.devices.setText(result.summary)
                for error in result.errors:
                    self.append(error + '\n')
                ok = not result.errors
            except (ValueError, KeyError, TypeError) as error:
                self.append('Could not read device list: ' + str(error) + '\n')
                ok = False
        self.status.setText(('Devices refreshed' if inventory else 'Finished — see output')
                           if ok else 'Failed — see output and logs')
        self.set_busy(False)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.append('Could not start command: ' + self.process.errorString() + '\n')
            self.status.setText('Could not start')
            self.set_busy(False)
