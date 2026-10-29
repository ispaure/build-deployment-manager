"""Saved-preset controls and lifecycle for one run workspace."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QMenu, QToolButton


class PresetController(QObject):
    def __init__(self, registry, key, panel, guarded):
        super().__init__(panel)
        self.registry, self.key, self.panel = registry, key, panel
        self.guarded = guarded
        self.presets = dict(registry.read()['projects'][key].get('presets', {}))
        # Keep presets on their own row for native laptop font metrics.
        row = QHBoxLayout()
        panel.configuration.intent_header.layout().addLayout(row)
        self.picker = QComboBox()
        self.picker.setAccessibleName('Saved project run presets')
        self.picker.setMinimumContentsLength(32)
        self.picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.picker.setToolTip('Load saved choices')
        self.picker.addItem('Presets…', None)
        for name in self.presets:
            self.picker.addItem(name, name)
        row.addWidget(self.picker)
        self.menu_button = QToolButton()
        self.menu_button.setText('⋯')
        self.menu_button.setAccessibleName('Save or delete run presets')
        menu = QMenu(self.menu_button)
        self.actions = {name: menu.addAction(name) for name in ('Save preset…', 'Delete preset')}
        self.menu_button.setMenu(menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self.menu_button)
        panel.busy_changed.connect(self.set_busy)
        panel.selection_changed.connect(self.refresh_state)
        self.picker.currentIndexChanged.connect(self.refresh_state)
        self.picker.activated.connect(lambda *_: self.guarded(self.load_selected, panel))
        self.actions['Save preset…'].triggered.connect(lambda: self.guarded(self.save_selected, panel))
        self.actions['Delete preset'].triggered.connect(lambda: self.guarded(self.delete_selected, panel))
        panel.configuration.run_fields.defaults_loaded.connect(self.match_restored)
        self.match_restored()

    def matches(self, name):
        return self.panel.configuration.preset_matches(self.presets[name])

    def refresh_state(self, *_):
        picker = self.picker
        name = picker.currentData()
        modified = name in self.presets and not self.matches(name)
        for index in range(1, picker.count()):
            label = picker.itemData(index)
            picker.setItemText(index, label + (' · Modified' if label == name and modified else ''))
            picker.setItemData(index, picker.itemText(index), Qt.ItemDataRole.ToolTipRole)
        picker.setToolTip(picker.currentText() if name is not None else 'Load saved choices')
        picker.setAccessibleDescription(picker.toolTip())
        self.actions['Delete preset'].setEnabled(name is not None and picker.isEnabled())

    def set_busy(self, busy):
        self.picker.setEnabled(not busy)
        self.menu_button.setEnabled(not busy)
        self.actions['Save preset…'].setEnabled(not busy)
        self.actions['Delete preset'].setEnabled(not busy and self.picker.currentData() is not None)

    def load_selected(self):
        name = self.picker.currentData()
        if name is None:
            return
        choices = self.registry.read()['projects'][self.key]['presets'][name]
        self.panel.restore_selection(choices)
        self.panel.status.setText('Loaded preset: ' + name + '. Review the plan before running.')
        self.refresh_state()

    def save_selected(self):
        if self.panel.configuration.defaults_loading():
            raise ValueError('Project defaults are still loading. Save the preset once they have loaded.')
        name, accepted = QInputDialog.getText(self.panel.window(), 'Save run preset',
            'Preset name (an existing name replaces that preset):', text=self.picker.currentData() or '')
        if not accepted:
            return
        choices = self.panel.configuration.preset_snapshot()
        self.registry.save_preset(self.key, name, choices)
        name = name.strip()
        self.presets[name] = choices
        if self.picker.findData(name) < 0:
            self.picker.addItem(name, name)
        self.picker.setCurrentIndex(self.picker.findData(name))
        self.refresh_state()
        self.panel.status.setText('Saved private run preset: ' + name)

    def delete_selected(self):
        name = self.picker.currentData()
        if name is not None:
            self.registry.delete_preset(self.key, name)
            self.presets.pop(name, None)
            self.picker.removeItem(self.picker.currentIndex())
            self.picker.setCurrentIndex(0)

    def refresh(self):
        current = self.picker.currentData()
        self.presets = dict(self.registry.read()['projects'][self.key].get('presets', {}))
        self.picker.blockSignals(True)
        try:
            self.picker.clear()
            self.picker.addItem('Presets…', None)
            for name in self.presets:
                self.picker.addItem(name, name)
            self.picker.setCurrentIndex(max(0, self.picker.findData(current)))
        finally:
            self.picker.blockSignals(False)
        self.refresh_state()

    def match_restored(self, *_):
        # Defaults arrive asynchronously; never replace an explicit selection.
        if self.picker.currentData() is None:
            match = next((name for name in self.presets if self.matches(name)), None)
            if match is not None:
                self.picker.setCurrentIndex(self.picker.findData(match))
        self.refresh_state()
