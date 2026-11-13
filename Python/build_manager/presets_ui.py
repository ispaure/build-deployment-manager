"""One preset picker and the per-run baseline for its selected preset."""
from PySide6.QtCore import QObject, QSignalBlocker, Qt
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QToolButton
from shiboken6 import isValid


class PresetController(QObject):
    def __init__(self, registry, key, panel, guarded):
        super().__init__(panel)
        self.panel, self.guarded = panel, guarded
        self.registry, self.key, self.owner = registry, key, None
        self.after_flush = None
        self.configuration = panel.configuration
        self.picker = self.configuration.preset
        self.menu_button = self.configuration.preset_menu
        self.work_type = self.configuration.goal
        self.suggestions = getattr(panel.project, 'workflow_presets', {})
        self.presets = {}
        self.active_choice = ('custom', None)
        self.baseline = None
        self.saved_version = None
        self.goal_open = False
        self.editable = True
        menu = QMenu(self.menu_button)
        self.actions = {}
        for name, action in (
            ('Reset overrides', self.reset_overrides),
            ('Save changes to selected preset…', self.save_changes),
            ('Save as new preset…', self.save_new),
            ('Delete preset', self.delete_selected),
        ):
            item = menu.addAction(name)
            item.triggered.connect(lambda checked=False, action=action: self.guarded(action, self.panel))
            self.actions[name] = item
        self.menu_button.setMenu(menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        panel.busy_changed.connect(self.set_busy)
        panel.selection_changed.connect(self.refresh_state)
        self.picker.currentIndexChanged.connect(self.choose_preset)
        self.picker.activated.connect(self.choice_activated)
        self.configuration.override_goal.clicked.connect(self.open_goal_override)
        self.work_type.activated.connect(self.finish_goal_override)
        self.work_type.currentIndexChanged.connect(self.refresh_state)
        self.configuration.run_fields.defaults_loaded.connect(self.refresh_state)
        menu.aboutToShow.connect(self.refresh_state)
        self.populate(self.active_choice)
        self.refresh_state()

    def bind_registry(self, registry, key, guarded, after_flush, owner):
        self.registry, self.key, self.guarded, self.owner = registry, key, guarded, owner
        self.after_flush = after_flush
        self.presets = dict(getattr(self.panel.project, 'row', {}).get('presets', {}))
        self.populate(self.active_choice)
        self.match_restored()

    def choice_at(self, index):
        kind = self.picker.itemData(index, Qt.ItemDataRole.UserRole + 1)
        return kind, self.picker.itemData(index)

    def populate(self, current):
        with QSignalBlocker(self.picker):
            self.picker.clear()
            self.add_choice('custom', None, 'Custom run')
            for kind, choices, heading in (
                ('private', self.presets, 'Private presets'),
                ('suggestion', self.suggestions, 'Project suggestions'),
            ):
                if not choices:
                    continue
                index = self.picker.count()
                self.picker.addItem(heading)
                item = self.picker.model().item(index)
                item.setEnabled(False)
                item.setSelectable(False)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                for name in choices:
                    self.add_choice(kind, name, name)
            self.set_picker(current)

    def add_choice(self, kind, name, label):
        self.picker.addItem(label, name)
        self.picker.setItemData(self.picker.count() - 1, kind, Qt.ItemDataRole.UserRole + 1)

    def set_picker(self, choice):
        index = next((index for index in range(self.picker.count()) if self.choice_at(index) == choice), 0)
        with QSignalBlocker(self.picker):
            self.picker.setCurrentIndex(index)

    def choose_preset(self, index):
        choice = self.choice_at(index)
        if choice[0] is None or not self.editable:
            self.set_picker(self.active_choice)
        elif choice != self.active_choice:
            self.guarded(lambda: self.load_choice(choice), self.panel)
            if self.active_choice != choice:
                self.set_picker(self.active_choice)

    def choice_activated(self, _):
        kind, name = self.active_choice
        if self.editable and kind == 'private' and self.saved_version != self.presets[name]:
            self.guarded(lambda: self.load_choice(self.active_choice), self.panel)

    def load_choice(self, choice):
        kind, name = choice
        if kind == 'private':
            self.panel.preset_error = ''
            self.panel.restore_selection(self.presets[name])
        elif kind == 'suggestion':
            self.panel.select_preset(name)
        elif self.panel.preset_error:
            self.panel.preset_error = ''
            self.panel.invalidate()
        self.active_choice = choice
        self.saved_version = self.presets[name] if kind == 'private' else None
        self.goal_open = False
        self.set_picker(choice)
        self.capture_baseline()
        self.refresh_state()

    def capture_baseline(self):
        kind, name = self.active_choice
        if kind == 'custom' or self.panel.preset_error:
            self.baseline = None
            return
        choices = self.configuration.choices()
        if kind == 'private':
            # Fields absent from an older preset still inherit their project
            # defaults. Other sparse choices keep the effective values shown
            # when the preset was selected.
            choices['run_overrides'] = dict(self.presets[name].get('run_overrides', {}))
        self.baseline = choices

    def refresh_state(self, *_):
        kind, name = self.active_choice
        selected = kind != 'custom'
        private = kind == 'private'
        error = self.panel.preset_error
        overridden = self.baseline is not None and not self.configuration.preset_matches(self.baseline)
        configuration = self.configuration
        configuration.preset_work_type.setText(self.work_type.currentText())
        configuration.preset_work_type.setVisible(selected and not self.goal_open)
        self.work_type.setVisible(not selected or self.goal_open)
        self.work_type.setEnabled(self.editable and (not selected or self.goal_open))
        configuration.override_goal.setVisible(selected and not self.goal_open and not error)
        configuration.override_goal.setEnabled(self.editable)
        configuration.preset_note.setVisible(overridden)
        changed_elsewhere = private and self.saved_version != self.presets.get(name)
        description = 'Private preset' if private else 'Project suggestion' if selected else 'Custom run'
        if changed_elsewhere:
            description += '. Saved choices changed. Select this preset again to load them.'
        self.picker.setToolTip(description)
        self.picker.setAccessibleDescription(description)
        self.menu_button.setVisible(self.registry is not None or selected)
        defaults_ready = not configuration.defaults_loading()
        can_write = (self.registry is not None and self.editable and not getattr(self.panel, 'is_busy', False)
                     and not self.panel.closing)
        reset = self.editable and (overridden or self.goal_open or bool(error))
        save = can_write and not error and defaults_ready
        self.menu_button.setEnabled(can_write or reset)
        self.actions['Reset overrides'].setEnabled(reset)
        self.actions['Save changes to selected preset…'].setEnabled(
            save and private and overridden and not changed_elsewhere)
        self.actions['Save as new preset…'].setEnabled(save)
        self.actions['Delete preset'].setEnabled(can_write and private and not changed_elsewhere)

    def set_busy(self, busy):
        self.editable = not busy or bool(self.panel.preparing and not self.panel.preparing_verification
                                         and not self.panel.closing)
        self.picker.setEnabled(self.editable)
        self.refresh_state()

    def open_goal_override(self):
        self.goal_open = True
        self.refresh_state()
        self.work_type.setFocus()

    def finish_goal_override(self, _):
        if self.goal_open:
            self.goal_open = False
            self.refresh_state()

    def reset_overrides(self):
        kind, name = self.active_choice
        if self.baseline is None:
            if kind == 'suggestion':
                self.load_choice(self.active_choice)
            return
        self.panel.restore_selection(self.baseline)
        self.goal_open = False
        self.refresh_state()

    def write(self, action):
        # Capture the operation before waiting for the remembered-choice
        # writer. Registry mutations then use the same lock without competing.
        def run():
            panel = self.panel if isValid(self.panel) and not self.panel.closing else None
            self.guarded(action, panel)
        self.after_flush(run)

    def save_new(self):
        origin = self.active_choice
        choices = self.configuration.preset_snapshot()
        name, accepted = QInputDialog.getText(self.panel.window(), 'Save as new preset', 'Preset name:')
        if not accepted:
            return
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('Enter a preset name of 1–100 characters.')
        self.write(lambda: self.save(origin, name, choices, choices, replace=False))

    def save_changes(self):
        origin = self.active_choice
        kind, name = origin
        if kind != 'private':
            return
        expected = self.saved_version
        snapshot = self.configuration.preset_snapshot()
        choices = self.configuration.update_preset(expected, self.baseline, snapshot)
        snapshot['run_overrides'] = choices.get('run_overrides', {})
        if QMessageBox.question(self.panel.window(), 'Save preset changes',
                f'Save the current run choices to the private preset “{name}”?') == QMessageBox.StandardButton.Yes:
            self.write(lambda: self.save(origin, name, choices, snapshot, replace=True, expected=expected))

    def save(self, origin, name, choices, baseline, *, replace, expected=None):
        from .registry import Registry
        Registry.validate_selections(choices)

        def update(data):
            presets = data['projects'][self.key].setdefault('presets', {})
            if not replace and name in presets:
                raise ValueError('A private preset with that name already exists. Choose a new name.')
            if replace and presets.get(name) != expected:
                raise ValueError('This private preset changed. Select it again before saving changes.')
            presets[name] = choices
            return dict(presets)

        presets = self.registry.mutate(update)
        if isValid(self.panel) and not self.panel.closing:
            if self.active_choice == origin:
                self.active_choice = ('private', name)
                self.saved_version = choices
                self.goal_open = False
                # The current draft can change while the captured save is queued.
                self.baseline = baseline
            if not getattr(self.panel, 'is_busy', False):
                self.panel.status.setText('Saved private preset: ' + name)
        self.update_presets(presets)

    def delete_selected(self):
        kind, name = self.active_choice
        if kind == 'private':
            expected = self.saved_version
            def delete():
                def update(data):
                    presets = data['projects'][self.key].get('presets', {})
                    if name in presets and presets[name] != expected:
                        raise ValueError('This private preset changed. Select it again before deleting.')
                    presets.pop(name, None)
                    return dict(presets)
                self.update_presets(self.registry.mutate(update))
            self.write(delete)

    def update_presets(self, presets):
        for dock in self.owner.run_workspace.all_docks:
            controller = getattr(dock.widget(), 'preset_controller', None)
            if controller is not None and controller.key == self.key:
                controller.replace_presets(presets)

    def replace_presets(self, presets):
        kind, name = self.active_choice
        # Existing drafts continue from the preset values they loaded, even if
        # another tab later saves changes under that name.
        self.presets = dict(presets)
        if kind == 'private' and name not in self.presets:
            self.active_choice = ('custom', None)
            self.baseline = None
            self.saved_version = None
            self.goal_open = False
        self.populate(self.active_choice)
        self.refresh_state()

    def refresh(self):
        if self.registry is not None:
            self.replace_presets(self.registry.read()['projects'][self.key].get('presets', {}))

    def match_restored(self):
        if self.active_choice[0] == 'custom':
            name = next((name for name, choices in self.presets.items()
                         if self.configuration.preset_matches(choices)), None)
            if name is not None:
                self.active_choice = ('private', name)
                self.saved_version = self.presets[name]
                self.set_picker(self.active_choice)
                self.capture_baseline()
        self.refresh_state()
