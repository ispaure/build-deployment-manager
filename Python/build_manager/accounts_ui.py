"""Protected account references; no secret entry or unavailable store setup."""
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFileDialog,
    QFormLayout,QLabel,QLineEdit,QPushButton,QVBoxLayout,QMessageBox)
from .settings import SettingsStore,reference_status


class AccountsDialog(QDialog):
    def __init__(self,store=None,project=None,parent=None):
        super().__init__(parent)
        self.store=store or SettingsStore();self.project=project
        self.setWindowTitle('Accounts · protected references')
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.accounts=QComboBox();self.accounts.addItem('New account reference','')
        for key,row in self.store.read()['accounts'].items():self.accounts.addItem(key,key)
        self.name=QLineEdit();self.provider=QComboBox();self.provider.addItems(['github','firebase','testflight'])
        self.kind=QComboBox();self.kind.addItems(['protected-file','credential-helper','environment-name','firebase-cli'])
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
        self.status.setText(reference_status(self.reference.text())+'. Provider read access and signing are verified separately by the project; publish permission is not implied.')

    def save(self):
        try:
            key=self.name.text().strip()
            if not key:raise ValueError('Choose an account reference name.')
            self.store.account(key,provider=self.provider.currentText(),kind=self.kind.currentText(),reference=self.reference.text())
            if self.project:self.store.select_account(self.project,key)
        except (OSError,ValueError,RuntimeError) as error:
            QMessageBox.warning(self,'Reference not saved',str(error));return
        self.accept()
