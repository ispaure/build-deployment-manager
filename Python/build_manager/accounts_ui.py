"""Protected account references; no secret entry or unavailable store setup."""
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFileDialog,
    QFormLayout,QLabel,QLineEdit,QPushButton,QVBoxLayout,QMessageBox)
from .settings import SettingsStore,reference_status


class AccountsDialog(QDialog):
    def __init__(self,store=None,project=None,parent=None,*,providers=None):
        super().__init__(parent)
        self.store=store or SettingsStore();self.project=project
        self.providers=tuple(providers or ('github','firebase','testflight'))
        self.setWindowTitle('Accounts · protected references')
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.accounts=QComboBox();self.accounts.addItem('New account reference','')
        for key,row in self.store.read()['accounts'].items():
            if row['provider'] in self.providers:self.accounts.addItem(key,key)
        self.name=QLineEdit();self.provider=QComboBox();self.provider.addItems(self.providers)
        self.kind=QComboBox();self.kind.addItems(['credential-helper','environment-name'])
        self.provider.currentTextChanged.connect(self.provider_changed)
        self.provider_changed()
        self.reference=QLineEdit();self.status=QLabel('References only. Destinations and signing identities remain project-owned.')
        self.status.setWordWrap(True)
        for label,control in [('Account',self.accounts),('Reference name',self.name),('Provider',self.provider),
                              ('Reference kind',self.kind),('Protected reference',self.reference)]:form.addRow(label,control)
        browse=QPushButton('Browse / Locate');browse.clicked.connect(self.browse);form.addRow(browse)
        verify=QPushButton('Inspect reference availability');verify.clicked.connect(self.inspect);form.addRow(verify)
        layout.addWidget(self.status)
        self.accounts.currentIndexChanged.connect(self.selected)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def provider_changed(self,*_):
        choices={'github':('credential-helper','environment-name'),'firebase':('firebase-cli',),'testflight':('protected-file',)}
        self.kind.clear();self.kind.addItems(choices[self.provider.currentText()])

    def selected(self,*_):
        key=self.accounts.currentData()
        if not key:return
        row=self.store.read()['accounts'][key]
        self.name.setText(key);self.provider.setCurrentText(row['provider'])
        self.kind.setCurrentText(row['kind']);self.reference.setText(row['reference'])

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Locate an existing protected credential reference')
        if path:self.reference.setText(path)

    def inspect(self):
        import os,shutil
        kind=self.kind.currentText()
        if kind=='protected-file':status=reference_status(self.reference.text())
        elif kind=='environment-name':status='configured' if os.environ.get(self.reference.text()) else 'missing environment reference'
        elif kind=='credential-helper':status='Git helper reference configured; login not verified' if shutil.which('git') else 'Git is unavailable'
        else:status='Existing Firebase CLI authentication reference; verify it through the project'
        self.status.setText(status+'. Provider read access and signing are verified separately; publish permission is not implied.')

    def save(self):
        try:
            key=self.name.text().strip()
            if not key:raise ValueError('Choose an account reference name.')
            self.store.account(key,provider=self.provider.currentText(),kind=self.kind.currentText(),reference=self.reference.text())
            if self.project:self.store.select_account(self.project,key)
        except (OSError,ValueError,RuntimeError) as error:
            QMessageBox.warning(self,'Reference not saved',str(error));return
        self.accept()
