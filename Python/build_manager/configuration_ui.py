"""Configuration widgets expose values; the panel owns planning policy."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget)


class ConfigurationView(QScrollArea):
    names = ('preset', 'operation', 'platform', 'backend', 'suite', 'revision',
             'pattern', 'build_override', 'release_tag', 'run_controls', 'advanced_toggle')

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        configuration = QWidget()
        self.setWidget(configuration)
        self.body_layout = configuration_layout = QVBoxLayout(configuration)
        guidance = QLabel('1. Choose a workflow or operation.  2. Inspect its source, gates and destination.  '
                          '3. Run preparation and tests.  4. Review and continue any delivery steps.')
        guidance.setWordWrap(True)
        configuration_layout.addWidget(guidance)
        form = QFormLayout()
        advanced_form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem('Custom operation')
        self.preset.addItems(getattr(project, 'workflow_presets', {}))
        form.addRow('Workflow preset', self.preset)
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
                    'GitHub release tag': 'Explicit unused release tag for a Release operation, such as v0.1.15-alpha.39.',
                }[label])
            (form if control in (self.operation, self.platform, self.backend) else advanced_form).addRow(label, control)
        form.addRow('Test suite', self.suite)
        self.run_controls = {}
        for name, entry in getattr(project, 'run_options', {}).items():
            control = QCheckBox(entry['label'])
            control.setChecked(entry.get('default', False))
            self.run_controls[name] = control
            form.addRow(control)
        configuration_layout.addLayout(form)
        self.advanced_toggle = QCheckBox('Advanced options: source, focused tests and release identifiers')
        advanced = QWidget()
        advanced.setLayout(advanced_form)
        advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        configuration_layout.addWidget(self.advanced_toggle)
        configuration_layout.addWidget(advanced)
        configuration_layout.addStretch()

    def choices(self):
        return dict(suite=self.suite.currentData() or '', **{
            name: getattr(self, name).currentText() if name in ('operation', 'platform', 'backend')
            else getattr(self, name).text()
            for name in ('operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag')})
