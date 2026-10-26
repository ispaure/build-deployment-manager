"""Inputs for this run, initialized asynchronously from project defaults."""
from queue import Queue,Empty
from threading import Event
from PySide6.QtCore import QRunnable,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import QWidget,QFormLayout,QLabel,QLineEdit,QPlainTextEdit


class ReadDefaults(QRunnable):
    def __init__(self, project, results, cancelled):
        super().__init__();self.project,self.results,self.cancelled=project,results,cancelled
    def run(self):
        try:self.results.put((self.project.run_defaults(cancelled=self.cancelled.is_set),None))
        except Exception as error:self.results.put(({},str(error)))


class RunFieldsView(QWidget):
    defaults_loaded = Signal()
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.fields=getattr(project,'run_fields',[])
        self.controls,self.labels,self.edited={},{},set()
        self.form=QFormLayout(self)
        self.form.setContentsMargins(0,0,0,0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.status=QLabel('For this run only. Saved project defaults stay unchanged.')
        self.status.setWordWrap(True);self.form.addRow(self.status)
        for row in self.fields:
            field=QPlainTextEdit() if row.get('kind')=='multiline' else QLineEdit()
            if isinstance(field,QPlainTextEdit):field.setFixedHeight(95)
            field.setAccessibleName(row['label'])
            field.setProperty('runField',row['id'])
            field.setPlaceholderText(row.get('description','Uses the saved default unless you change it for this run.'))
            field.textChanged.connect(self.mark_edited)
            label=QLabel(row['label']);label.setWordWrap(True)
            self.form.addRow(label,field)
            self.controls[row['id']],self.labels[row['id']]=field,label
        self.results=Queue();self.cancelled=Event();self.timer=QTimer(self)
        self.timer.setInterval(50);self.timer.timeout.connect(self.loaded)
        if self.fields and hasattr(project,'run_defaults'):
            self.timer.start();QThreadPool.globalInstance().start(ReadDefaults(project,self.results,self.cancelled))
        self.setVisible(False)

    def mark_edited(self):
        self.edited.add(self.sender().property('runField'))

    def loaded(self):
        try:values,error=self.results.get_nowait()
        except Empty:return
        self.timer.stop()
        if self.cancelled.is_set():return
        if error:
            self.status.setText('Saved defaults could not be loaded. You can enter values for this run or check Project settings.')
            return
        for name,value in values.items():
            if name in self.controls and name not in self.edited:
                field=self.controls[name];field.blockSignals(True)
                field.setPlainText(str(value)) if isinstance(field,QPlainTextEdit) else field.setText(str(value))
                field.blockSignals(False)
        self.defaults_loaded.emit()

    def update_context(self, goal, destinations, operation):
        visible=False
        for row in self.fields:
            active=(goal=='deliver' and bool(set(row.get('destinations',[])) & set(destinations))
                    or goal=='advanced' and operation in row.get('operations',[]))
            self.form.setRowVisible(self.labels[row['id']],active)
            visible=visible or active
        self.setVisible(visible)
        self.updateGeometry()

    def values(self):
        result={}
        for name,field in self.controls.items():
            if not self.form.isRowVisible(self.labels[name]):continue
            value=field.toPlainText() if isinstance(field,QPlainTextEdit) else field.text()
            if value.strip() or name in self.edited:result[name]=value
        return result

    def stop(self):
        self.cancelled.set();self.timer.stop()
