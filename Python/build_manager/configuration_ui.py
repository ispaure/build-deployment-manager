"""Configuration widgets expose values; the panel owns planning policy."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget)


class ConfigurationView(QWidget):
    names = ('preset', 'operation', 'platform', 'backend', 'suite', 'revision',
             'pattern', 'build_override', 'release_tag', 'run_controls', 'advanced_toggle',
             'goal', 'platform_checks', 'platform_backends', 'destination_checks', 'readiness', 'preset_note', 'run_fields')

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.body_layout = configuration_layout = QVBoxLayout(self)
        configuration_layout.setContentsMargins(0,0,0,0)
        guidance = QLabel('Choose what to test, then press Next to review the plan. '
                          'A passing test never starts an upload or device install automatically.')
        guidance.setWordWrap(True)
        configuration_layout.addWidget(guidance)
        self.goal = QComboBox()
        self.goal.setAccessibleName('What would you like to do?')
        self.goal.addItem('Validate — run checks only', 'validate')
        self.goal.addItem('Validate and deliver — check, prepare, then review delivery', 'deliver')
        self.goal.addItem('Advanced operation — project workflow or single operation', 'advanced')
        configuration_layout.addWidget(QLabel('What would you like to do?'))
        configuration_layout.addWidget(self.goal)
        self.guided = QWidget()
        guided_layout = QVBoxLayout(self.guided)
        guided_layout.setContentsMargins(0, 0, 0, 0)
        self.platform_checks, self.platform_backends, self.destination_checks = {}, {}, {}
        self.delivery_widgets = []
        capability = getattr(project, 'journey_capability', None)
        self.selectable_backends = bool(capability and capability.get('selectable_backends'))
        if capability:
            guided_layout.addWidget(QLabel('Test these platforms · choose where each one runs'))
            for target, row in capability['platforms'].items():
                control = QCheckBox(row.get('label', target))
                control.setAccessibleName('Validate ' + target)
                control.setChecked(False)
                self.platform_checks[target] = control
                choices = tuple(project.backend_options(target, row['operation']))
                location = QComboBox()
                location.setAccessibleName('Run '+target+' tests on')
                location.addItems(choices)
                if location.findText(row['backend']) < 0:
                    location.addItem(row['backend'])
                location.setCurrentText(row['backend'])
                location.setEnabled(False)
                self.platform_backends[target] = location
                platform_row = QHBoxLayout()
                platform_row.addWidget(control,1)
                platform_row.addWidget(location,1)
                guided_layout.addLayout(platform_row)
            heading = QLabel('Where should successful builds go? Confirm exact recipients in the plan.')
            guided_layout.addWidget(heading)
            self.delivery_widgets.append(heading)
            for name, row in capability.get('destinations', {}).items():
                control = QCheckBox(row['label'])
                control.setToolTip(row.get('description', '') + ' Requires: ' + ', '.join(row['platforms']))
                self.destination_checks[name] = control
                guided_layout.addWidget(control)
                self.delivery_widgets.append(control)
                explanation = QLabel(row.get('description', '') + ' Requires: ' + ', '.join(row['platforms']))
                explanation.setWordWrap(True)
                guided_layout.addWidget(explanation)
                self.delivery_widgets.append(explanation)
        else:
            note = QLabel('This project supports one platform per run. Choose Advanced operation for its delivery workflows. '
                          'Combined validation and delivery needs support from the project maintainer.')
            note.setWordWrap(True)
            guided_layout.addWidget(note)
        configuration_layout.addWidget(self.guided)
        self.readiness = QLabel()
        self.readiness.setWordWrap(True)
        self.readiness.setAccessibleName('Selected work and readiness')
        configuration_layout.addWidget(self.readiness)
        self.legacy = QWidget()
        legacy_layout = QVBoxLayout(self.legacy)
        legacy_layout.setContentsMargins(0, 0, 0, 0)
        self.legacy_form = form = QFormLayout()
        advanced_form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem('Custom operation')
        self.preset.addItems(getattr(project, 'workflow_presets', {}))
        form.addRow('Suggested workflow', self.preset)
        self.preset_note = QLabel('Choose a suggested workflow or configure an advanced operation.')
        self.preset_note.setWordWrap(True)
        form.addRow(self.preset_note)
        self.restore_preset = QPushButton('Restore suggested workflow')
        form.addRow(self.restore_preset)
        self.operation = QComboBox()
        self.operation.addItems(project.operations)
        self.platform = QComboBox()
        self.platform.addItems(project.platforms)
        self.backend = QComboBox()
        self.suite = QComboBox()
        self.suite.setAccessibleName('Test suite')
        self.revision = QLineEdit('working-tree')
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText('Blank: full declared suite; filename glob: focused contracts')
        self.build_override = QSpinBox()
        self.build_override.setRange(0, 2147483647)
        self.build_override.setSpecialValueText('Automatic')
        self.build_override.setToolTip('Zero selects automatic allocation. A positive number overrides this run only; existing build numbers cannot be reused.')
        self.release_tag = QLineEdit()
        self.release_tag.setPlaceholderText('Explicit release identifier supplied by the project policy')
        for label, control in [('Platform', self.platform), ('Operation', self.operation),
                               ('Backend', self.backend), ('Source revision', self.revision),
                               ('Focused test pattern', self.pattern), ('Build number override', self.build_override),
                               ('GitHub release tag', self.release_tag)]:
            control.setAccessibleName(label)
            if control is not self.build_override:
                control.setToolTip({
                    'Operation': 'Choose tests, an artifact build, tester preparation or a GitHub release. Inspect the plan before running.',
                    'Platform': 'Operating system to build or test.',
                    'Backend': 'Where the operation runs. VM backends require an explicitly configured authorized test VM.',
                    'Source revision': 'working-tree includes current edits; a Git revision selects that committed source.',
                    'Focused test pattern': 'Optional test filename glob for desktop contracts. Blank runs the full declared suite.',
                    'GitHub release tag': 'Optional custom release identifier. Leave blank to use the project’s automatic naming policy.',
                }[label])
            if control is not self.release_tag:
                (form if control in (self.operation, self.platform, self.backend) else advanced_form).addRow(label, control)
        form.addRow('Test suite', self.suite)
        self.run_controls = {}
        for name, entry in getattr(project, 'run_options', {}).items():
            control = QCheckBox(entry['label'])
            control.setChecked(entry.get('default', False))
            self.run_controls[name] = control
            form.addRow(control)
        legacy_layout.addLayout(form)
        configuration_layout.addWidget(self.legacy)
        # Source identity stays visible; custom release naming is optional.
        self.source_summary = QLabel()
        self.source_summary.setWordWrap(True)
        configuration_layout.addWidget(self.source_summary)
        self.release_tag.setAccessibleName('Release identifier for this run')
        self.release_tag.setPlaceholderText('Automatic · the project chooses the next release identifier')
        self.advanced_toggle = QCheckBox('Advanced options: source revision, focused checks and build number')
        advanced = QWidget()
        advanced.setLayout(advanced_form)
        advanced_form.addRow(QLabel('Leave the release identifier blank for automatic naming.'))
        advanced_form.addRow('Custom release identifier',self.release_tag)
        advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        configuration_layout.addWidget(self.advanced_toggle)
        configuration_layout.addWidget(advanced)
        from .run_fields_ui import RunFieldsView
        self.run_fields = RunFieldsView(project,self)
        configuration_layout.addWidget(self.run_fields)
        self.goal.currentIndexChanged.connect(self.update_mode)
        self.revision.textChanged.connect(self.update_summary)
        for control in (*self.platform_checks.values(), *self.destination_checks.values()):
            control.toggled.connect(self.update_mode)
        for location in self.platform_backends.values():
            location.currentTextChanged.connect(self.location_changed)
        self.operation.currentTextChanged.connect(self.update_mode)
        self.update_mode()

    def ensureWidgetVisible(self, widget):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent,QScrollArea):
                parent.ensureWidgetVisible(widget);return
            parent = parent.parentWidget()

    def location_changed(self, *_):
        if any(self.platform_checks[name].isChecked() and location.currentText() == 'GitHub'
                for name,location in self.platform_backends.items()) and self.revision.text() == 'working-tree':
            self.revision.setText('HEAD')
        self.update_summary()

    def update_mode(self, *_):
        integrated = bool(self.platform_checks) and self.goal.currentData() != 'advanced'
        self.guided.setVisible(self.goal.currentData() != 'advanced')
        self.legacy.setVisible(not integrated)
        for control in (self.preset, self.preset_note, self.restore_preset, self.operation):
            self.legacy_form.setRowVisible(control, self.goal.currentData() == 'advanced')
        for widget in self.delivery_widgets:
            widget.setVisible(self.goal.currentData() == 'deliver')
        for target, location in self.platform_backends.items():
            location.setEnabled(self.platform_checks[target].isChecked() and self.selectable_backends)
        for control in self.destination_checks.values():
            control.setEnabled(self.goal.currentData() == 'deliver')
        self.location_changed()
        if hasattr(self,'run_fields'):
            self.run_fields.update_context(self.goal.currentData(),
                [name for name,control in self.destination_checks.items() if control.isChecked()],self.operation.currentText())
        self.updateGeometry()

    def update_summary(self, *_):
        self.source_summary.setText('Source for this run: ' + (self.revision.text() or 'Choose a source revision'))
        if any(self.platform_checks[name].isChecked() and choice.currentText()=='GitHub'
                for name,choice in self.platform_backends.items()):
            self.source_summary.setText(self.source_summary.text()+' · GitHub runs committed source; local edits are excluded.')
        targets = [name for name, control in self.platform_checks.items() if control.isChecked()]
        destinations = [name for name, control in self.destination_checks.items() if control.isChecked()]
        if self.platform_checks and self.goal.currentData() != 'advanced':
            self.readiness.setText('Selected platforms: ' + (', '.join(targets) or 'None — select at least one') +
                '. Delivery: ' + (', '.join(destinations) if self.goal.currentData() == 'deliver' and destinations else 'none') +
                '. Next: check hosts, prepare the plan and review exact source and recipients.')
        else:
            self.readiness.setText('Next: prepare and review the project-declared plan. Review lists required checks, '
                                   'execution hosts, delivery actions and their approval points.')

    def choices(self):
        return dict(suite=self.suite.currentData() or '', goal=self.goal.currentData(),
            platform_backends={name:control.currentText() for name,control in self.platform_backends.items()},
            selected_platforms=[name for name, control in self.platform_checks.items() if control.isChecked()],
            selected_destinations=[name for name, control in self.destination_checks.items() if control.isChecked()], **{
            name: getattr(self, name).currentText() if name in ('operation', 'platform', 'backend')
            else getattr(self, name).text()
            for name in ('operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag')})
