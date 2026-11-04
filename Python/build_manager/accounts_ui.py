"""Protected account references; no secret entry or unavailable store setup."""
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFileDialog,
    QFormLayout,QLabel,QLineEdit,QPushButton,QVBoxLayout,QMessageBox)
from .settings import SettingsStore,reference_status
from .ui_components import style_dialog_buttons, style_utilities


class AccountsDialog(QDialog):
    def __init__(self,store=None,project=None,parent=None,*,providers=None):
        super().__init__(parent)
        self.store=store or SettingsStore();self.project=project
        self.providers=tuple(providers or ('github','firebase','testflight'))
        self.setWindowTitle('Connected accounts')
        self.resize(560, 440)
        layout=QVBoxLayout(self);layout.setSpacing(12)
        form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);form.setVerticalSpacing(12);layout.addLayout(form)
        self.form = form
        intro=QLabel('Choose an existing login method or credential file. '
                    'Project settings controls where builds go; an account does not choose a destination.')
        intro.setWordWrap(True);layout.insertWidget(0,intro)
        self.accounts=QComboBox();self.accounts.addItem('New account reference','')
        for key,row in self.store.read()['accounts'].items():
            if row['provider'] in self.providers:self.accounts.addItem(key,key)
        self.name=QLineEdit();self.provider=QComboBox();self.provider.addItems(self.providers)
        self.kind=QComboBox();self.kind.addItems(['credential-helper','environment-name'])
        self.provider.currentTextChanged.connect(self.provider_changed)
        self.reference=QLineEdit();self.status=QLabel('References only. Destinations and signing identities remain project-owned.')
        self.reference.setPlaceholderText('File path or environment variable name · never paste a token')
        self.status.setWordWrap(True)
        for label,control in [('Account',self.accounts),('Reference name',self.name),('Provider',self.provider),
                              ('Login method',self.kind),('Protected reference',self.reference)]:form.addRow(label,control)
        self.name.setPlaceholderText('For example: Internal QA')
        self.method_help = QLabel();self.method_help.setWordWrap(True);form.addRow(self.method_help)
        browse=self.browse_button=QPushButton('Choose credential file…');browse.clicked.connect(self.browse);form.addRow(browse)
        self.kind.currentTextChanged.connect(self.reference_kind_changed)
        self.provider_changed()
        self.reference_kind_changed()
        verify=QPushButton('Check reference');verify.clicked.connect(self.inspect);form.addRow(verify)
        layout.addWidget(self.status)
        self.accounts.currentIndexChanged.connect(self.selected)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        style_dialog_buttons(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        style_utilities(self)

    def reference_kind_changed(self, *_):
        kind = self.kind.currentData()
        self.form.setRowVisible(self.browse_button, kind == 'protected-file')
        self.form.setRowVisible(self.reference, kind in {'protected-file', 'environment-name'})
        self.reference.setPlaceholderText('Existing protected file path' if kind == 'protected-file' else 'Environment variable name, e.g. GH_TOKEN')
        self.method_help.setText({
            'credential-helper': 'Uses your existing Git credential helper. Checking this reference does not verify provider login.',
            'firebase-cli': 'Uses an existing Firebase CLI login; the project verifies access separately.',
            'environment-name': 'Enter the variable name only. Credential contents are never entered here.',
            'protected-file': 'Choose an existing protected credential file. Its contents are never copied into settings.',
        }.get(kind, ''))

    def provider_changed(self,*_):
        choices={'github':('credential-helper','environment-name'),'firebase':('firebase-cli',),'testflight':('protected-file',)}
        labels = {'credential-helper': 'Existing Git credential helper', 'environment-name': 'Environment variable name',
                  'firebase-cli': 'Existing Firebase CLI login', 'protected-file': 'Protected credential file'}
        self.kind.clear()
        for kind in choices[self.provider.currentText()]: self.kind.addItem(labels[kind], kind)

    def selected(self,*_):
        key=self.accounts.currentData()
        if not key:
            self.name.clear();self.reference.clear()
            return
        row=self.store.read()['accounts'][key]
        self.name.setText(key);self.provider.setCurrentText(row['provider'])
        self.kind.setCurrentIndex(self.kind.findData(row['kind']));self.reference.setText(row['reference'])

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Locate an existing protected credential reference')
        if path:self.reference.setText(path)

    def inspect(self):
        import os,shutil
        kind=self.kind.currentData()
        if kind=='protected-file':status=reference_status(self.reference.text())
        elif kind=='environment-name':status='configured' if os.environ.get(self.reference.text()) else 'missing environment reference'
        elif kind=='credential-helper':status='Git helper reference configured; login not verified' if shutil.which('git') else 'Git is unavailable'
        else:status='Existing Firebase CLI authentication reference; verify it through the project'
        self.status.setText(status+'. Provider read access and signing are verified separately; publish permission is not implied.')

    def save(self):
        try:
            key=self.name.text().strip()
            if not key:raise ValueError('Choose an account reference name.')
            kind = self.kind.currentData()
            reference = self.reference.text()
            self.store.save_account_reference(key,provider=self.provider.currentText(),kind=kind,reference=reference)
            if self.project:self.store.bind_project_account(self.project,key)
        except (OSError,ValueError,RuntimeError) as error:
            QMessageBox.warning(self,'Reference not saved',str(error));return
        self.accept()
