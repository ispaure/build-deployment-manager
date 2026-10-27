"""Inputs for this run, initialized asynchronously from project defaults."""
from queue import Queue,Empty
from threading import Event
from PySide6.QtCore import QRunnable,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import QWidget,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QComboBox


class RunChoice(QComboBox):
    textChanged = Signal(str)

    def __init__(self, row):
        super().__init__()
        for key, label in row['options'].items():self.addItem(label, key)
        self.setCurrentIndex(self.findData(row['default']))
        self.currentIndexChanged.connect(lambda _: self.textChanged.emit(self.text()))

    def text(self):return self.currentData()

    def setText(self, value):
        index = self.findData(value)
        if index >= 0:self.setCurrentIndex(index)

    def setPlaceholderText(self, value):self.setToolTip(value)


class ReadDefaults(QRunnable):
    def __init__(self, project, results, cancelled):
        super().__init__();self.project,self.results,self.cancelled=project,results,cancelled
    def run(self):
        try:self.results.put((self.project.run_defaults(cancelled=self.cancelled.is_set),None))
        except Exception as error:self.results.put(({},str(error)))


class ReadChoices(QRunnable):
    def __init__(self, project, results, cancelled):
        super().__init__(); self.project, self.results, self.cancelled = project, results, cancelled
    def run(self):
        try:self.results.put((self.project.run_choices(cancelled=self.cancelled.is_set), None))
        except Exception as error:self.results.put(({}, str(error)))


class RunFieldsView(QWidget):
    defaults_loaded = Signal()
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.fields=getattr(project,'run_fields',[])
        self.controls,self.labels,self.edited={},{},set()
        self.defaults = {}
        self.destination_forms, self.field_forms, self.active_fields = {}, {}, set()
        self.workflow_form = None
        self.form=QFormLayout(self)
        self.form.setContentsMargins(0,0,0,0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.status=QLabel('Run choices are remembered on this computer. Project defaults stay unchanged.')
        self.status.setWordWrap(True);self.form.addRow(self.status)
        from .recipient_ui import RecipientPicker
        for row in self.fields:
            field=(RunChoice(row) if row.get('kind') == 'choice' else RecipientPicker() if row.get('kind') == 'multiselect' else
                   QPlainTextEdit() if row.get('kind')=='multiline' else QLineEdit())
            if isinstance(field, RecipientPicker):
                field.reload_requested.connect(self.reload_choices)
            if isinstance(field,QPlainTextEdit):field.setFixedHeight(95)
            field.setAccessibleName(row['label'])
            field.setProperty('runField',row['id'])
            field.setPlaceholderText(row.get('description','Uses the saved default unless you change it for this run.'))
            field.textChanged.connect(self.mark_edited)
            label=QLabel(row['label']);label.setWordWrap(True)
            self.form.addRow(label,field)
            self.controls[row['id']],self.labels[row['id']]=field,label
            self.field_forms[row['id']] = self.form
        self.results=Queue();self.cancelled=Event();self.timer=QTimer(self)
        self.timer.setInterval(50);self.timer.timeout.connect(self.loaded)
        if self.fields and hasattr(project,'run_defaults'):
            self.timer.start();QThreadPool.globalInstance().start(ReadDefaults(project,self.results,self.cancelled))
        self.project = project
        self.choice_results = Queue(); self.choice_timer = QTimer(self)
        self.choice_timer.setInterval(50); self.choice_timer.timeout.connect(self.choices_loaded)
        if any(row.get('kind') == 'multiselect' for row in self.fields):
            self.reload_choices()
        self.setVisible(False)

    def reload_choices(self):
        if self.choice_timer.isActive():return
        if not hasattr(self.project, 'run_choices'):
            self.choice_results.put(({}, None)); self.choices_loaded(); return
        self.choice_timer.start()
        QThreadPool.globalInstance().start(ReadChoices(self.project, self.choice_results, self.cancelled))

    def choices_loaded(self):
        try:rows,error = self.choice_results.get_nowait()
        except Empty:return
        self.choice_timer.stop()
        if self.cancelled.is_set():return
        from .recipient_ui import RecipientPicker
        from .run_fields import selection_ids
        for name, field in self.controls.items():
            if not isinstance(field, RecipientPicker):continue
            choices = rows.get(name, []) if isinstance(rows, dict) else []
            valid = isinstance(choices, list) and len(choices) <= 50
            try:
                if not valid or any(not isinstance(row, dict) or not isinstance(row.get('label'), str) for row in choices):
                    raise ValueError('Invalid recipient list.')
                import json
                selection_ids(json.dumps([row.get('id') for row in choices]))
                field.set_choices(choices)
            except ValueError:
                error = 'The project returned an invalid saved device list.'
            if error:
                field.note.setText('Saved devices could not be loaded. Reload or enter an already paired, connected device ID.')
                from .redaction import Redactor
                field.note.setToolTip(Redactor()(error))
        self.defaults_loaded.emit()

    def mark_edited(self):
        self.edited.add(self.sender().property('runField'))

    def loaded(self):
        try:values,error=self.results.get_nowait()
        except Empty:return
        self.timer.stop()
        if self.cancelled.is_set():return
        if error:
            self.status.setText('Saved defaults could not be loaded. You can enter values for this run or check Project settings.')
            self.setVisible(bool(self.active_fields))
            return
        self.defaults = dict(values)
        for name,value in values.items():
            if name in self.controls and name not in self.edited:
                field=self.controls[name];field.blockSignals(True)
                field.setPlainText(str(value)) if isinstance(field,QPlainTextEdit) else field.setText(str(value))
                field.blockSignals(False)
        self.defaults_loaded.emit()

    def set_destination_forms(self, forms):
        self.destination_forms = forms

    def set_workflow_form(self, form):
        self.workflow_form = form

    def update_context(self, goal, destinations, operation):
        visible=False
        self.active_fields.clear()
        for row in self.fields:
            active=(row.get('workflow_option', False)
                    or goal=='deliver' and bool(set(row.get('destinations',[])) & set(destinations))
                    or goal=='advanced' and operation in row.get('operations',[]))
            name = row['id']
            destination = row.get('destinations', [])
            target = (self.destination_forms.get(destination[0], self.form)
                      if goal == 'deliver' and len(destination) == 1 else self.form)
            if row.get('workflow_option') and self.workflow_form is not None and goal != 'advanced':
                target = self.workflow_form
            if self.field_forms[name] is not target:
                self.field_forms[name].takeRow(self.labels[name])
                target.addRow(self.labels[name], self.controls[name])
                self.field_forms[name] = target
            target.setRowVisible(self.labels[name], active)
            if active:
                self.active_fields.add(name)
            visible = visible or (active and target is self.form)
        self.setVisible(visible or (bool(self.active_fields) and 'could not be loaded' in self.status.text()))
        self.updateGeometry()

    def restore(self, values):
        from .run_fields import validate_overrides
        # Ignore fields removed by a newer project descriptor.
        values = {name: value for name, value in values.items() if name in self.controls}
        # A preset saved before an option existed uses its declared default;
        # it must not inherit the previous preset's debug-only override.
        for row in self.fields:
            if row.get('workflow_option'):
                values.setdefault(row['id'], row.get('default', ''))
        validate_overrides(self.fields, values)
        for name, value in values.items():
            self.edited.add(name)  # Pending defaults must not overwrite restored choices.
            field = self.controls[name]
            field.setPlainText(value) if isinstance(field, QPlainTextEdit) else field.setText(value)

    def saved_values(self):
        return {name: field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()
                for name, field in self.controls.items() if name in self.edited}

    def values(self):
        result={}
        for name,field in self.controls.items():
            if name not in self.active_fields:continue
            value=field.toPlainText() if isinstance(field,QPlainTextEdit) else field.text()
            if value.strip() or name in self.edited:result[name]=value
        return result

    def missing_selection(self):
        row = self.missing_selection_field()
        return 'Choose at least one recipient for ' + row['label'] + '.' if row else ''

    def missing_selection_field(self):
        from .run_fields import selection_ids
        for row in self.fields:
            if row['id'] in self.active_fields and row.get('kind') == 'multiselect':
                if not selection_ids(self.controls[row['id']].text()):
                    return row
        return None

    def stop(self):
        self.cancelled.set();self.timer.stop();self.choice_timer.stop()
