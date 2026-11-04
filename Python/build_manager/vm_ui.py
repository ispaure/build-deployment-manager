"""Non-blocking controls for this checkout's two dedicated test VMs."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                              QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QMessageBox,
                              QWidget, QScrollArea, QDialogButtonBox)
from .ui_components import style_button, WrappingLayout, HeadingLabel, style_utilities, style_dialog_buttons
from .review_ui import Disclosure


class VMWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, kind, root, action, media=None, digest='', parent=None):
        super().__init__(parent)
        self.kind, self.root, self.action, self.media, self.digest = kind, root, action, media, digest

    def run(self):
        from .vm import LinuxVM, WindowsVM
        from .redaction import Redactor
        try:
            vm = (LinuxVM if self.kind == 'Linux' else WindowsVM)(self.root, event=self.progress.emit)
            if self.action == 'initialize':
                result = vm.initialize(self.media, self.digest)
            elif self.action == 'initialize-cloud':
                if self.kind != 'Linux': raise ValueError('Fedora cloud initialization requires Linux.')
                result = vm.initialize_cloud(self.media, self.digest)
            elif self.action == 'initialize-windows':
                if self.kind != 'Windows': raise ValueError('Windows initialization requires Windows.')
                result = vm.initialize_unattended(self.media, self.digest)
            elif self.action == 'enable-guest-commands':
                result = vm.enable_guest_commands(approved=True)
            elif self.action == 'enable-symlink-testing':
                if self.kind != 'Windows': raise ValueError('Symlink policy requires Windows.')
                result = vm.enable_symlink_testing(approved=True)
            elif self.action == 'open-console':
                result = vm.open_console()
            elif self.action in ('start', 'stop'):
                result = vm.power(self.action)
            else:
                result = getattr(vm, self.action)()
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(Redactor()(str(error)))


class VMDialog(QDialog):
    def __init__(self, parent=None, checkout=None):
        super().__init__(parent)
        self.worker = None
        self.setWindowTitle('Dedicated test machines')
        self.resize(760, 600)
        outer = QVBoxLayout(self)
        outer.addWidget(HeadingLabel('Dedicated test machines'))
        scope = QLabel('Machines owned by the manager checkout. Status is read only when requested.')
        scope.setWordWrap(True)
        outer.addWidget(scope)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        row = QHBoxLayout(); self.checkout = QLineEdit()
        candidate = Path(checkout) if checkout else Path(__file__).resolve().parents[2]
        if (candidate / 'Python/build_manager').is_dir(): self.checkout.setText(str(candidate))
        self.checkout.setAccessibleName('Manager source checkout for VM storage')
        choose = QPushButton('Choose manager checkout'); choose.clicked.connect(self.choose_checkout)
        row.addWidget(self.checkout, 1); row.addWidget(choose); layout.addLayout(row)
        self.kind = QComboBox(); self.kind.addItems(['Linux', 'Windows'])
        self.kind.setAccessibleName('Dedicated test machine operating system'); layout.addWidget(self.kind)
        self.details = QLabel('Choose a machine, then Refresh status. Personal and held machines are never adopted.')
        self.details.setWordWrap(True); self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.next_action_name = 'status'
        self.next_action = style_button(QPushButton('Refresh status'), 'primary')
        self.next_action.clicked.connect(lambda: self.launch(self.next_action_name))
        layout.addWidget(self.next_action, 0, Qt.AlignmentFlag.AlignLeft)
        actions = WrappingLayout(); self.buttons = [choose, self.next_action]
        self.actions = {}
        for label, action in [('Refresh status', 'status'), ('Create or recover', 'ensure'),
                              ('Open console', 'open-console'), ('Start', 'start'), ('Check readiness', 'readiness'), ('Shut down', 'stop')]:
            button = style_button(QPushButton(label))
            button.clicked.connect(lambda checked=False, action=action: self.launch(action))
            actions.addWidget(button); self.buttons.append(button); self.actions[action] = button
        layout.addLayout(actions)
        setup = QWidget(); setup_layout = QVBoxLayout(setup); setup_layout.setSpacing(12)
        control = QPushButton('Allow guest test commands…'); control.clicked.connect(self.approve_commands)
        setup_layout.addWidget(control); self.buttons.append(control)
        self.symlinks = QPushButton('Allow Windows filesystem tests…'); self.symlinks.clicked.connect(self.approve_symlinks)
        setup_layout.addWidget(self.symlinks); self.buttons.append(self.symlinks)
        setup_layout.addWidget(QLabel('Verified operating system media'))
        self.iso = QLineEdit(); self.iso.setPlaceholderText('ISO or cloud image path')
        self.iso.setAccessibleName('Operating system installation media')
        setup_layout.addWidget(self.iso)
        browse = QPushButton('Choose OS media'); browse.clicked.connect(self.choose_media)
        setup_layout.addWidget(browse); self.buttons.append(browse)
        self.digest = QLineEdit(); self.digest.setPlaceholderText('SHA-256 published by the OS vendor')
        self.digest.setAccessibleName('Vendor installer SHA-256'); setup_layout.addWidget(self.digest)
        attach = QPushButton('Verify and attach installer'); attach.clicked.connect(lambda: self.launch('initialize'))
        setup_layout.addWidget(attach); self.buttons.append(attach)
        self.initializers = {}
        for label, action, kind in [('Initialize Fedora cloud image', 'initialize-cloud', 'Linux'), ('Initialize fresh Windows guest', 'initialize-windows', 'Windows')]:
            button = QPushButton(label); button.clicked.connect(lambda checked=False, action=action: self.launch(action))
            setup_layout.addWidget(button); self.buttons.append(button); self.initializers[kind] = button
        self.setup_section = Disclosure('Installation and advanced permissions', setup)
        layout.addWidget(self.setup_section)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); self.output.setMaximumBlockCount(300)
        self.output.setMinimumHeight(160)
        self.output.setAccessibleName('VM setup progress and errors')
        self.log_section = Disclosure('Progress and error log', self.output)
        layout.addWidget(self.log_section)
        note = QLabel('Readiness reports the actual OS, architecture, Python and Git. It does not certify native tests or acceleration.')
        note.setWordWrap(True); layout.addWidget(note); layout.addStretch()
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject); outer.addWidget(self.close_buttons)
        style_dialog_buttons(self.close_buttons)
        style_utilities(self)
        self.kind.currentTextChanged.connect(self.kind_changed)
        self.kind_changed()

    def kind_changed(self, *_):
        kind = self.kind.currentText()
        self.symlinks.setVisible(kind == 'Windows')
        for target, button in self.initializers.items(): button.setVisible(target == kind)
        self.next_action_name = 'status'
        self.next_action.setText('Refresh status')
        self.actions['status'].hide()
        for action in ('ensure', 'start', 'readiness'): self.actions[action].show()
        self.details.setText('Refresh ' + kind + ' status to see the next setup task. Personal and held machines are never adopted.')

    def choose_checkout(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose the manager source checkout')
        if path: self.checkout.setText(path)

    def choose_media(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose verified OS media', '', 'OS images (*.iso *.qcow2)')
        if path: self.iso.setText(path)

    def launch(self, action):
        if self.worker and self.worker.isRunning(): return
        root = Path(self.checkout.text()).expanduser()
        if not (root / 'Python/build_manager').is_dir():
            self.output.appendPlainText('Choose a manager source checkout first.'); return
        self.log_section.toggle.setChecked(True)
        self.close_buttons.setEnabled(False)
        for control in [*self.buttons, self.kind, self.checkout, self.iso, self.digest]: control.setEnabled(False)
        self.worker = VMWorker(self.kind.currentText(), root, action, self.iso.text(), self.digest.text().strip(), self)
        self.worker.progress.connect(self.output.appendPlainText)
        self.worker.failed.connect(lambda error: self.output.appendPlainText('Setup needs attention: ' + error))
        self.worker.completed.connect(self.show_result)
        self.worker.finished.connect(self.finish)
        self.output.appendPlainText(action.replace('ensure', 'Create or recover') + '…')
        self.worker.start()

    def approve_commands(self):
        if QMessageBox.question(self, 'Allow guest commands for this dedicated machine?',
                f"Enable Parallels guest-command control for Build Deployment Manager ({self.kind.currentText()})? "
                'This turns off blanket VM isolation. Host folders, profile, clipboard and cloud sharing stay disabled. '
                'Only the owned machine at this checkout’s recorded UUID will be changed.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.launch('enable-guest-commands')

    def show_result(self, result):
        import json
        states={'running':'Running','stopped':'Shut down','missing':'Not created'}
        setup={'not-created':'Create this machine to begin','installation-required':'OS installation required',
               'first-boot-required':'Finish OS setup','test-tools-ready':'Test tools ready'}
        self.details.setText(f"{result['name']} · {states.get(result['state'],result['state'])} · {setup.get(result['setup'],result['setup'])}\n{result['requirements']}\n{result['storage']}")
        self.next_action_name = ('ensure' if result['state'] == 'missing' else
            'open-console' if result['setup'] in {'installation-required', 'first-boot-required'} else
            'start' if result['state'] == 'stopped' else 'readiness')
        self.next_action.setText({'ensure': 'Create or recover', 'open-console': 'Finish OS setup in console',
                                 'start': 'Start machine', 'readiness': 'Check readiness'}[self.next_action_name])
        for action, button in self.actions.items():
            button.setVisible(action != self.next_action_name)
        self.output.appendPlainText(json.dumps(result, indent=2))

    def approve_symlinks(self):
        if self.kind.currentText() != 'Windows':
            self.output.appendPlainText('Select Windows to configure filesystem testing.'); return
        if QMessageBox.question(self, 'Allow Windows symbolic links?',
                'Enable Developer Mode for this checkout’s owned Windows test machine? '
                'This lets the normal test user create symbolic links. The approval is saved '
                'for future recreation of this machine. Host sharing stays disabled.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.launch('enable-symlink-testing')

    def finish(self):
        self.close_buttons.setEnabled(True)
        for control in [*self.buttons, self.kind, self.checkout, self.iso, self.digest]: control.setEnabled(True)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.output.appendPlainText('Wait for the bounded VM operation to finish before closing.'); return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning(): event.ignore()
        else: super().closeEvent(event)
