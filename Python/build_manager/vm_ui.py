"""Non-blocking controls for this checkout's two dedicated test VMs."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                              QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QMessageBox)


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
        layout = QVBoxLayout(self)
        intro = QLabel('Prepare a Fedora or Windows test machine. Create or recover reuses this checkout’s owned machine, '
                       'or creates a fresh one when missing. OS installation, guest tools and readiness checks are separate steps. '
                       'VM files and private setup records stay in the checkout’s ignored VM folder.')
        intro.setWordWrap(True); layout.addWidget(intro)
        row = QHBoxLayout(); self.checkout = QLineEdit()
        candidate = Path(checkout) if checkout else Path(__file__).resolve().parents[2]
        if (candidate / 'Python/build_manager').is_dir(): self.checkout.setText(str(candidate))
        self.checkout.setAccessibleName('Manager source checkout for VM storage')
        choose = QPushButton('Choose manager checkout'); choose.clicked.connect(self.choose_checkout)
        row.addWidget(self.checkout, 1); row.addWidget(choose); layout.addLayout(row)
        self.kind = QComboBox(); self.kind.addItems(['Linux', 'Windows'])
        self.kind.setAccessibleName('Dedicated test machine operating system'); layout.addWidget(self.kind)
        self.details = QLabel('Choose a machine, then Refresh status. Existing personal and held machines are never adopted.')
        self.details.setWordWrap(True); self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        actions = QHBoxLayout(); self.buttons = [choose]
        for label, action in [('Refresh status', 'status'), ('Create or recover', 'ensure'),
                              ('Open console', 'open-console'), ('Start', 'start'), ('Check readiness', 'readiness'), ('Shut down', 'stop')]:
            button = QPushButton(label); button.clicked.connect(lambda checked=False, action=action: self.launch(action))
            actions.addWidget(button); self.buttons.append(button)
        layout.addLayout(actions)
        control = QPushButton('Allow guest test commands…'); control.clicked.connect(self.approve_commands)
        layout.addWidget(control); self.buttons.append(control)
        symlinks = QPushButton('Allow Windows filesystem tests…'); symlinks.clicked.connect(self.approve_symlinks)
        layout.addWidget(symlinks); self.buttons.append(symlinks)
        media = QHBoxLayout(); self.iso = QLineEdit(); self.iso.setPlaceholderText('OS installer ISO path')
        self.iso.setAccessibleName('Operating system installer ISO')
        browse = QPushButton('Choose ISO'); browse.clicked.connect(self.choose_media)
        media.addWidget(self.iso, 1); media.addWidget(browse); layout.addLayout(media); self.buttons.append(browse)
        self.digest = QLineEdit(); self.digest.setPlaceholderText('SHA-256 published by the OS vendor')
        self.digest.setAccessibleName('Vendor installer SHA-256'); layout.addWidget(self.digest)
        attach = QPushButton('Verify and attach installer'); attach.clicked.connect(lambda: self.launch('initialize'))
        layout.addWidget(attach); self.buttons.append(attach)
        bootstrap = QHBoxLayout()
        for label, action in [('Initialize Fedora cloud image', 'initialize-cloud'), ('Initialize fresh Windows guest', 'initialize-windows')]:
            button = QPushButton(label); button.clicked.connect(lambda checked=False, action=action: self.launch(action))
            bootstrap.addWidget(button); self.buttons.append(button)
        layout.addLayout(bootstrap)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); self.output.setMaximumBlockCount(300)
        self.output.setAccessibleName('VM setup progress and errors'); layout.addWidget(self.output, 1)
        note = QLabel('Finish OS setup and install Parallels Tools in the dedicated guest. Readiness checks report the actual '
                      'OS, architecture, Python and Git; they do not mark native acceptance or Android acceleration as passed.')
        note.setWordWrap(True); layout.addWidget(note)

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
        for control in [*self.buttons, self.kind, self.checkout, self.iso, self.digest]: control.setEnabled(True)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.output.appendPlainText('Wait for the bounded VM operation to finish before closing.'); return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning(): event.ignore()
        else: super().closeEvent(event)
