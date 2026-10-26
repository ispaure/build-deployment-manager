"""Editable workflow intent beside a non-executable, live dependency sketch."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget, QTabWidget, QTableWidget, QHeaderView, QAbstractItemView)


class ConfigurationSection(QWidget):
    def __init__(self, label, *, expanded=True):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(label)
        self.toggle.setAccessibleName(label + ' settings section')
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self.expand)
        self.toggle.setChecked(expanded)
        self.expand(expanded)

    def expand(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def reveal(self):
        self.toggle.setChecked(True)


class ConfigurationView(QWidget):
    names = ('preset', 'operation', 'platform', 'backend', 'suite', 'revision',
             'pattern', 'build_override', 'release_tag', 'run_controls', 'advanced_toggle',
             'goal', 'platform_checks', 'platform_backends', 'destination_checks', 'readiness', 'preset_note', 'run_fields')

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(4)
        self.editor = QWidget()
        configuration_layout = QVBoxLayout(self.editor)
        configuration_layout.setContentsMargins(0, 0, 4, 0)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setWidget(self.editor)
        self.editor_scroll.setAccessibleName('Workflow configuration sections')
        self.editor_scroll.setMinimumWidth(350)
        from .workflow_ui import WorkflowFlow
        self.proposed_flow = WorkflowFlow()
        self.proposed_flow.setMinimumWidth(330)
        self.proposed_flow.phase_selected.connect(self.open_proposed_card)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(4, 0, 0, 0)
        heading = QLabel('Workflow overview')
        heading.setStyleSheet('font-weight: 600;')
        preview_layout.addWidget(heading)
        preview_layout.addWidget(self.proposed_flow, 1)
        self.proposal_detail = QLabel('')
        self.proposal_detail.setWordWrap(True)
        self.proposal_detail.setTextFormat(Qt.TextFormat.PlainText)
        preview_layout.addWidget(self.proposal_detail)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.editor_scroll)
        self.splitter.addWidget(preview)
        self.splitter.setSizes([510, 590])
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setMinimumHeight(420)
        self.body_layout.addWidget(self.splitter, 1)
        self.current_proposal = None
        self.last_opened_section = ''
        self._syncing_source = False
        self._custom_revision = ''
        self.sections = {}
        guidance = QLabel('Choose your settings, then review the plan before starting.')
        guidance.setWordWrap(True)
        guidance.hide()
        self.goal = QComboBox()
        self.goal.setAccessibleName('What would you like to do?')
        self.goal.addItem('Validate — run checks only', 'validate')
        self.goal.addItem('Validate and deliver', 'deliver')
        self.goal.addItem('Advanced operation — project workflow or single operation', 'advanced')
        configuration_layout.addWidget(QLabel('What would you like to do?'))
        configuration_layout.addWidget(self.goal)
        self.config_tabs = QTabWidget()
        self.config_tabs.setAccessibleName('Workflow configuration')
        self.config_pages, self.page_layouts = {}, {}
        for key, label in [('source', 'Source'), ('platforms', 'Testing'), ('delivery', 'Delivery'), ('advanced', 'Advanced')]:
            page = QWidget(); body = QVBoxLayout(page); body.setContentsMargins(4, 4, 4, 4); body.setSpacing(6)
            self.config_tabs.addTab(page, label); self.config_pages[key], self.page_layouts[key] = page, body
        configuration_layout.addWidget(self.config_tabs, 1)
        def section(key, label, expanded=True):
            item = ConfigurationSection(label, expanded=True)
            item.toggle.hide()
            self.sections[key] = item
            self.page_layouts['platforms' if key == 'validation' else key].addWidget(item)
            return item
        source = section('source', 'Source · which files to build')
        self.source_mode = QComboBox()
        self.source_mode.setAccessibleName('Source to build')
        self.source_mode.addItem('Current files — include uncommitted edits', 'working-tree')
        self.source_mode.addItem('Latest commit — exclude uncommitted edits', 'HEAD')
        self.source_mode.addItem('Specific commit, branch or tag', 'custom')
        self.revision = QLineEdit('working-tree')
        self.revision.setAccessibleName('Specific source revision')
        self.revision.setPlaceholderText('Commit SHA, branch or tag')
        self.source_form = QFormLayout()
        self.source_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.source_form.addRow('Build from', self.source_mode)
        self.source_form.addRow('Revision', self.revision)
        self.source_form.setRowVisible(self.revision, False)
        source.body.addLayout(self.source_form)
        self.source_summary = QLabel()
        self.source_summary.setWordWrap(True)
        self.source_summary.setTextFormat(Qt.TextFormat.PlainText)
        source.body.addWidget(self.source_summary)
        platforms = section('platforms', 'Platforms · what to test and where')
        self.guided = QWidget()
        guided_layout = QVBoxLayout(self.guided)
        guided_layout.setContentsMargins(0, 0, 0, 0)
        self.platform_checks, self.platform_backends, self.destination_checks = {}, {}, {}
        self.delivery_widgets = []
        self.destination_options, self.destination_forms, self.destination_groups = {}, {}, {}
        capability = getattr(project, 'journey_capability', None)
        self.selectable_backends = bool(capability and capability.get('selectable_backends'))
        self.platform_table = QTableWidget(0, 2)
        self.platform_table.setHorizontalHeaderLabels(['Platform', 'Test on'])
        self.platform_table.verticalHeader().hide()
        self.platform_table.setShowGrid(False)
        self.platform_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.platform_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.platform_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.platform_table.setAccessibleName('Platforms and testing locations')
        if capability:
            guided_layout.addWidget(self.platform_table)
            for target, row in capability['platforms'].items():
                control = QCheckBox(row.get('label', target).split(' (')[0])
                control.setAccessibleName('Validate ' + target)
                self.platform_checks[target] = control
                location = QComboBox()
                location.setAccessibleName('Run ' + target + ' tests on')
                location.addItems(tuple(project.backend_options(target, row['operation'])))
                if location.findText(row['backend']) < 0:
                    location.addItem(row['backend'])
                location.setCurrentText(row['backend'])
                location.setEnabled(False)
                self.platform_backends[target] = location
                index = self.platform_table.rowCount(); self.platform_table.insertRow(index)
                self.platform_table.setRowHeight(index, 38)
                self.platform_table.setCellWidget(index, 0, control)
                self.platform_table.setCellWidget(index, 1, location)
            self.platform_table.setMinimumHeight(38 * self.platform_table.rowCount() + 34)
            self.platform_table.setMaximumHeight(38 * self.platform_table.rowCount() + 34)
        else:
            note = QLabel('This project supports one platform per run. Advanced operation exposes its project workflows.')
            note.setWordWrap(True)
            guided_layout.addWidget(note)
        platforms.body.addWidget(self.guided)
        self.legacy = QWidget()
        legacy_layout = QVBoxLayout(self.legacy)
        legacy_layout.setContentsMargins(0, 0, 0, 0)
        self.legacy_form = form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.preset = QComboBox()
        self.preset.addItem('Custom operation')
        self.preset.addItems(getattr(project, 'workflow_presets', {}))
        form.addRow('Suggested workflow', self.preset)
        self.preset_note = QLabel('Choose a suggested workflow or configure an advanced operation.')
        self.preset_note.setWordWrap(True)
        form.addRow(self.preset_note)
        self.restore_preset = QPushButton('Restore suggested workflow')
        form.addRow(self.restore_preset)
        self.operation, self.platform, self.backend, self.suite = (QComboBox() for _ in range(4))
        self.operation.addItems(project.operations)
        self.platform.addItems(project.platforms)
        self.suite.setAccessibleName('Test suite')
        for label, control in [('Platform', self.platform), ('Operation', self.operation), ('Backend', self.backend)]:
            control.setAccessibleName(label)
            form.addRow(label, control)
        form.addRow('Test suite', self.suite)
        self.run_controls = {}
        for name, entry in getattr(project, 'run_options', {}).items():
            control = QCheckBox(entry['label'])
            control.setChecked(entry.get('default', False))
            self.run_controls[name] = control
            form.addRow(control)
        legacy_layout.addLayout(form)
        platforms.body.addWidget(self.legacy)
        validation = section('validation', 'Validation · required checks', expanded=False)
        self.require_validation = QCheckBox('Require the destination’s platform checks\nto pass before delivery')
        self.require_validation.setChecked(True)
        self.require_validation.setEnabled(False)
        self.require_validation.hide()
        note = QLabel('Delivery waits for its platform’s required tests. Independent branches can continue if another platform fails.')
        note.setWordWrap(True)
        validation.body.addWidget(note)
        delivery = section('delivery', 'Delivery · destinations and recipients')
        self.delivery_tabs = QTabWidget()
        self.delivery_categories, self.destination_categories = {}, {}
        if capability:
            delivery.body.addWidget(self.delivery_tabs)
            def category(label):
                if label not in self.delivery_categories:
                    page = QWidget(); body = QVBoxLayout(page); body.setContentsMargins(4, 4, 4, 4); body.setSpacing(4)
                    self.delivery_tabs.addTab(page, label.removeprefix('Mobile ').capitalize()); self.delivery_categories[label] = (page, body)
                return self.delivery_categories[label][1]
            categories = {'Mobile tester platforms': 0, 'Mobile dev devices': 1, 'Mobile stores': 2, 'Source releases': 3}
            for name, row in sorted(capability.get('destinations', {}).items(), key=lambda item: categories.get(item[1].get('category'), 4)):
                group = QWidget()
                group_layout = QVBoxLayout(group)
                group_layout.setContentsMargins(0, 0, 0, 4)
                group_layout.setSpacing(3)
                control = QCheckBox(row['label'])
                control.setToolTip('Select to show options. Requires: ' + ', '.join(row['platforms']))
                self.destination_checks[name] = control
                group_layout.addWidget(control)
                options = QWidget()
                options.setAccessibleName(row['label'] + ' options')
                options_layout = QVBoxLayout(options)
                options_layout.setContentsMargins(4, 0, 0, 0)
                explanation = QLabel(row.get('description', '') + ' Requires: ' + ', '.join(row['platforms']))
                explanation.setWordWrap(True)
                options_layout.addWidget(explanation)
                # Run-scoped guidance is shared once below the delivery choices.
                destination_form = QFormLayout()
                destination_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                destination_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                options_layout.addLayout(destination_form)
                self.destination_options[name], self.destination_forms[name] = options, destination_form
                self.destination_groups[name] = group
                group_layout.addWidget(options)
                label = row.get('category', 'Destinations')
                category(label).addWidget(group)
                self.destination_categories[name] = label
                self.delivery_widgets.append(group)
            for row in capability.get('unavailable_destinations', []):
                label = QLabel(row['label'] + ' · unavailable in this workflow\n' + row['reason'])
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)
                category(row.get('category', 'Destinations')).addWidget(label)
            for page, body in self.delivery_categories.values():body.addStretch()
            for index, label in enumerate(sorted(self.delivery_categories, key=lambda name: categories.get(name, 4))):
                current = self.delivery_tabs.indexOf(self.delivery_categories[label][0])
                self.delivery_tabs.tabBar().moveTab(current, index)
        else:
            note = QLabel('Integrated delivery is not declared by this project. Choose Advanced operation for its existing workflows.')
            note.setWordWrap(True)
            delivery.body.addWidget(note)
        from .run_fields_ui import RunFieldsView
        self.run_fields = RunFieldsView(project, self)
        self.run_fields.set_destination_forms(self.destination_forms)
        delivery.body.addWidget(self.run_fields)
        advanced = section('advanced', 'Advanced options · focused checks and build numbers', expanded=False)
        self.advanced_toggle = advanced.toggle
        advanced_form = QFormLayout()
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText('Blank runs the full declared suite')
        self.build_override = QSpinBox()
        self.build_override.setRange(0, 2147483647)
        self.build_override.setSpecialValueText('Automatic')
        self.release_tag = QLineEdit()
        self.release_tag.setPlaceholderText('Automatic · project naming policy')
        for label, control in [('Focused test pattern', self.pattern), ('Build number override', self.build_override),
                               ('Custom release identifier', self.release_tag)]:
            control.setAccessibleName(label)
            advanced_form.addRow(label, control)
        advanced.body.addLayout(advanced_form)
        self.readiness = QLabel()
        self.readiness.setWordWrap(True)
        self.readiness.setTextFormat(Qt.TextFormat.PlainText)
        self.readiness.setAccessibleName('Proposed choices and unresolved requirements')
        configuration_layout.addWidget(self.readiness)
        for body in self.page_layouts.values():body.addStretch()
        self.source_mode.currentIndexChanged.connect(self.choose_source)
        self.revision.textChanged.connect(self.source_revision_changed)
        self.goal.currentIndexChanged.connect(self.update_mode)
        for control in (*self.platform_checks.values(), *self.destination_checks.values()):
            control.toggled.connect(self.update_mode)
        for location in self.platform_backends.values():
            location.currentTextChanged.connect(self.location_changed)
        for control in (self.operation, self.platform, self.backend, self.suite):
            control.currentIndexChanged.connect(self.update_mode)
        for control in self.run_fields.controls.values():
            control.textChanged.connect(self.refresh_proposal)
        self.run_fields.defaults_loaded.connect(self.refresh_proposal)
        self.update_mode()

    def choose_source(self, *_):
        if self._syncing_source:
            return
        value = self.source_mode.currentData()
        self._syncing_source = True
        try:
            if value != 'custom':
                self.revision.setText(value)
            elif self.revision.text() in ('working-tree', 'HEAD'):
                self.revision.setText(self._custom_revision)
        finally:
            self._syncing_source = False
        self.source_form.setRowVisible(self.revision, value == 'custom')
        self.update_summary()

    def source_revision_changed(self, *_):
        if not self._syncing_source and not (self.source_mode.currentData() == 'custom' and self.revision.hasFocus()):
            self._syncing_source = True
            try:
                value = self.revision.text()
                self.source_mode.setCurrentIndex(self.source_mode.findData(value if value in ('working-tree', 'HEAD') else 'custom'))
            finally:
                self._syncing_source = False
            self.source_form.setRowVisible(self.revision, self.source_mode.currentData() == 'custom')
        if self.source_mode.currentData() == 'custom' and self.revision.text() not in ('working-tree', 'HEAD'):
            self._custom_revision = self.revision.text()
        self.update_summary()

    def ensureWidgetVisible(self, widget):
        if self.editor.isAncestorOf(widget):
            self.editor_scroll.ensureWidgetVisible(widget, 16, 32)
            return
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget)
                return
            parent = parent.parentWidget()

    def location_changed(self, *_):
        # Source selection stays explicit: changing hosts must not silently exclude edits.
        self.update_summary()

    def update_mode(self, *_):
        integrated = bool(self.platform_checks) and self.goal.currentData() != 'advanced'
        self.guided.setVisible(self.goal.currentData() != 'advanced')
        self.legacy.setVisible(not integrated)
        for control in (self.preset, self.preset_note, self.restore_preset, self.operation):
            self.legacy_form.setRowVisible(control, self.goal.currentData() == 'advanced')
        self.sections['validation'].setVisible(self.goal.currentData() != 'advanced' and bool(self.platform_checks))
        self.sections['delivery'].setVisible(self.goal.currentData() == 'deliver')
        self.config_tabs.setTabEnabled(self.config_tabs.indexOf(self.config_pages['delivery']), self.goal.currentData() == 'deliver')
        for target, location in self.platform_backends.items():
            location.setEnabled(self.platform_checks[target].isChecked() and self.selectable_backends)
        for name, options in self.destination_options.items():
            options.setVisible(self.goal.currentData() == 'deliver' and self.destination_checks[name].isChecked())
        for control in self.destination_checks.values():
            control.setEnabled(self.goal.currentData() == 'deliver')
        field_body = self.sections['advanced' if self.goal.currentData() == 'advanced' else 'delivery'].body
        if self.goal.currentData() == 'deliver':
            categories = {self.destination_categories[name] for row in self.run_fields.fields
                if len(row.get('destinations', [])) > 1 for name in row['destinations']
                if name in self.destination_categories}
            if len(categories) == 1:
                field_body = self.delivery_categories[next(iter(categories))][1]
        field_body.insertWidget(max(0, field_body.count() - 1), self.run_fields)
        self.run_fields.update_context(self.goal.currentData(),
            [name for name, control in self.destination_checks.items() if control.isChecked()], self.operation.currentText())
        self.update_summary()

    def update_summary(self, *_):
        revision = self.revision.text()
        if revision == 'working-tree':
            text = 'Current files include uncommitted edits. Review checks whether the project permits this source for your selected work.'
        elif revision == 'HEAD':
            text = 'Latest commit: uncommitted edits are excluded. This does not commit or push anything.'
        else:
            text = 'Specific revision: ' + (revision or 'Enter a commit, branch or tag') + '. Uncommitted edits are excluded.'
        if any(self.platform_checks[name].isChecked() and choice.currentText() == 'GitHub'
               for name, choice in self.platform_backends.items()):
            text += ' GitHub runs committed source; local edits are excluded.'
        declared_policy = any('source_policy' in row for row in (getattr(self.project, 'journey_capability', None) or {}).get('destinations', {}).values())
        if revision == 'working-tree' and self.goal.currentData() == 'deliver' and not declared_policy:
            text += ' Delivery policy may require committed source. Latest commit excludes your edits without committing them.'
        self.source_summary.setText(text)
        self.refresh_proposal()

    def refresh_proposal(self):
        from .proposed_workflow import propose
        from .recipient_ui import RecipientPicker
        from .run_fields import selection_ids
        recipients = {}
        for name, field in self.run_fields.controls.items():
            if isinstance(field, RecipientPicker):
                labels = {row['id']: row['label'].removesuffix(' · saved') for row in field.choices()}
                recipients[name] = [labels.get(key, key) for key in selection_ids(field.text())]
        proposal = propose(capability=getattr(self.project, 'journey_capability', None), goal=self.goal.currentData(),
            revision=self.revision.text(), platforms=[name for name, item in self.platform_checks.items() if item.isChecked()],
            destinations=[name for name, item in self.destination_checks.items() if item.isChecked()],
            backends={name: item.currentText() for name, item in self.platform_backends.items()},
            operation=self.operation.currentText(), platform=self.platform.currentText(), backend=self.backend.currentText(), recipients=recipients, values=self.run_fields.values())
        self.readiness.setText('\n'.join(proposal.messages))
        self.readiness.setVisible(bool(proposal.messages))
        if proposal == self.current_proposal:
            return
        selected = self.proposed_flow.selected
        self.current_proposal = proposal
        self.proposed_flow.reset(proposal, preview=True)
        if selected in self.proposed_flow.canvas.cards:
            self.proposed_flow.selected = selected
            self.proposed_flow.set_facts({})
            node = next(node for node in proposal.phases if node.id == selected)
            self.proposal_detail.setText(node.label + ': ' + node.description + '. Settings are open on the left.')
        else:
            self.proposal_detail.setText('')

    def open_proposed_card(self, key):
        if not key:
            self.proposal_detail.setText('This is a proposal from your choices. Review checks project policy and resolves exact dependencies.')
            return
        node = next(node for node in self.current_proposal.phases if node.id == key)
        self.open_section(node.section, node.target)
        self.proposal_detail.setText(node.label + ': ' + node.description + '. Settings are open on the left.')

    def open_section(self, section, target=''):
        self.last_opened_section = section
        item = self.sections[section]
        item.reveal()
        self.config_tabs.setCurrentWidget(self.config_pages['platforms' if section == 'validation' else section])
        if section == 'delivery' and target in self.destination_categories:
            self.delivery_tabs.setCurrentWidget(self.delivery_categories[self.destination_categories[target]][0])
        if section == 'source':
            control = self.source_mode
        elif section == 'delivery' and target in self.destination_checks:
            control = next((self.run_fields.controls[row['id']] for row in self.run_fields.fields
                if row.get('destinations') == [target] and row['id'] in self.run_fields.active_fields),
                self.destination_checks[target])
        elif section == 'platforms' and target in self.platform_checks:
            control = self.platform_checks[target]
        else:
            control = item.toggle
        self.ensureWidgetVisible(control)
        control.setFocus(Qt.FocusReason.OtherFocusReason)

    def choices(self):
        return dict(build_override=self.build_override.value(),
            run_options={name: control.isChecked() for name, control in self.run_controls.items()},
            run_overrides=self.run_fields.saved_values(), suite=self.suite.currentData() or '', goal=self.goal.currentData(),
            platform_backends={name: control.currentText() for name, control in self.platform_backends.items()},
            selected_platforms=[name for name, control in self.platform_checks.items() if control.isChecked()],
            selected_destinations=[name for name, control in self.destination_checks.items() if control.isChecked()], **{
            name: getattr(self, name).currentText() if name in ('operation', 'platform', 'backend')
            else getattr(self, name).text()
            for name in ('operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag')})

    def restore_choices(self, choices):
        from .registry import Registry
        Registry.validate_selections(choices)
        from .run_fields import validate_overrides
        validate_overrides(self.run_fields.fields, {name: value for name, value in choices.get('run_overrides', {}).items()
                                                  if name in self.run_fields.controls})
        # Restore dependent controls in a stable order, independent of JSON key order.
        for name in ('platform', 'operation', 'backend', 'suite', 'goal', 'revision', 'pattern', 'release_tag'):
            if name not in choices:
                continue
            control, value = getattr(self, name), choices[name]
            if name in ('suite', 'goal'):
                control.setCurrentIndex(max(0, control.findData(value)))
            elif name in ('platform', 'operation', 'backend'):
                if control.findText(value) < 0:
                    control.addItem(value)
                control.setCurrentText(value)
            else:
                control.setText(value)
        for name, controls in (('selected_platforms', self.platform_checks), ('selected_destinations', self.destination_checks)):
            if name in choices:
                for identifier, control in controls.items():
                    control.setChecked(identifier in choices[name])
        for target, value in choices.get('platform_backends', {}).items():
            if target in self.platform_backends:
                control = self.platform_backends[target]
                if control.findText(value) < 0:
                    control.addItem(value)
                control.setCurrentText(value)
        self.build_override.setValue(choices.get('build_override', 0))
        for name, control in self.run_controls.items():
            control.setChecked(choices.get('run_options', {}).get(name, self.project.run_options[name].get('default', False)))
        # A preset is a complete set of run inputs. Clear edits omitted by it.
        for name, field in self.run_fields.controls.items():
            if name in self.run_fields.edited and name not in choices.get('run_overrides', {}):
                from PySide6.QtWidgets import QPlainTextEdit
                value = str(self.run_fields.defaults.get(name, '[]' if next(row for row in self.run_fields.fields if row['id'] == name).get('kind') == 'multiselect' else ''))
                field.setPlainText(value) if isinstance(field, QPlainTextEdit) else field.setText(value)
                self.run_fields.edited.discard(name)
        self.run_fields.restore(choices.get('run_overrides', {}))
        self.update_mode()
