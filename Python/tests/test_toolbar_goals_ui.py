"""Visible intent, contextual presets and compact navigation over unchanged requests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from build_manager.app import ManagerWindow
from build_manager.registry import Registry
from test_ui import OtherProject
from test_journeys import CAPABILITY, integrated


class ToolbarGoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tooling_enabled = False
        self.suggestions = {}
        self.data = dict(projects={key: dict(name=key, root=str(self.root / key), presets={})
            for key in ('one', 'two')}, selected='one')
        owner = self
        class Store:
            def read(self): return deepcopy(owner.data)
            def select(self, key): owner.data['selected'] = key
            def resolve(self, key):
                return owner.data['projects'][key], dict(name=key, interpreter=OtherProject.interpreter)
            def save_selections(self, key, choices): owner.data['projects'][key]['selections'] = choices
            def save_preset(self, key, name, choices):
                Registry.validate_selections(choices)
                owner.data['projects'][key]['presets'][name.strip()] = deepcopy(choices)
            def delete_preset(self, key, name): owner.data['projects'][key]['presets'].pop(name)
            def mutate(self, update): return update(owner.data)
        def bridge(store, key):
            project = OtherProject(self.root)
            project.journey_capability = deepcopy(CAPABILITY)
            project.journey_capability['platforms']['ios']['label'] = 'iOS'
            project.row = deepcopy(self.data['projects'][key])
            project.workflow_presets = deepcopy(self.suggestions)
            project.operations = ('Test', 'Package')
            project.test_suites = [dict(id='package-checks', label='Package checks', tier='portable',
                                       platforms=['example'], operations=['Package'])]
            project.make_plan = Mock(side_effect=AssertionError('Intent must not start planning'))
            project.make_journey = Mock(side_effect=AssertionError('Intent must not start planning'))
            project.verification_plan = Mock(side_effect=AssertionError('Intent must not start verification'))
            if self.tooling_enabled:
                project.tooling_status = Mock(side_effect=AssertionError('Menu discovery must not call bootstrap'))
            return project
        factory = patch('build_manager.app.ProjectBridge', side_effect=bridge)
        factory.start()
        self.addCleanup(factory.stop)
        self.window = ManagerWindow(Store())
        self.addCleanup(self.window.close)
        self.panel = self.window.panel
        self.view = self.panel.configuration

    def test_compact_header_keeps_management_available_and_paths_on_demand(self):
        window = self.window
        self.assertEqual(window.controls.count(), 5)
        self.assertEqual(window.projects.currentText(), 'one')
        self.assertEqual(window.projects.toolTip(), str(self.root / 'one'))
        self.assertEqual(set(window.menu_actions), {'Add project…', 'Locate moved checkout…',
            'Remove registration', 'Accounts…', 'Test machines…', 'Check connections and settings…',
            'Manage build storage…', 'App settings…'})
        self.assertTrue(window.menu_actions['Manage build storage…'].isEnabled())
        self.assertNotIn('Project tooling…', window.menu_actions)
        self.assertIs(window.controls.itemAt(4).widget(), window.help_button)
        self.data['projects']['two']['name'] = 'one'
        window.refresh()
        self.assertNotEqual(window.projects.itemText(0), window.projects.itemText(1))

    def test_tooling_menu_is_present_only_when_the_project_opts_in(self):
        self.tooling_enabled = True
        window = ManagerWindow(self.window.registry)
        self.addCleanup(window.close)
        self.assertIn('Project tooling…', window.menu_actions)
        self.assertTrue(window.menu_actions['Project tooling…'].isEnabled())
        window.panel.project.tooling_status.assert_not_called()
        with patch.object(window, 'open_project_tooling') as open_tooling:
            window.menu_actions['Project tooling…'].trigger()
            open_tooling.assert_called_once_with(window.panel)

    def test_text_size_reaches_docked_controls_after_native_style_resolution(self):
        original = QFont(self.app.font())
        self.addCleanup(lambda: self.app.setFont(original))
        self.window.show(); self.app.processEvents()
        font = QFont(original); font.setPointSize(18); self.app.setFont(font)
        for _ in range(5): self.app.processEvents()
        for widget in (self.panel, self.view, self.view.source_mode, self.view.goal, self.panel.preset):
            self.assertEqual(widget.font().pointSizeF(), 18)

    def test_custom_run_work_types_share_existing_selection_and_keyboard_invalidation(self):
        panel, view = self.panel, self.view
        panel.plan = integrated(self.root)
        panel.start.setEnabled(True)
        self.window.show(); self.app.processEvents()
        self.assertEqual(panel.preset.currentText(), 'Custom run')
        self.assertTrue(view.goal.isVisible())
        self.assertTrue(all(button.isHidden() for button in view.goal_buttons.values()))
        view.goal.setFocus()
        QTest.keyClick(view.goal, Qt.Key.Key_Down)
        QTest.keyClick(view.goal, Qt.Key.Key_Down)
        self.assertEqual(panel.choices()['goal'], 'deliver')
        self.assertIsNone(panel.plan)
        self.assertFalse(panel.start.isEnabled())
        QTest.keyClick(view.goal, Qt.Key.Key_Down)
        self.assertEqual(panel.choices()['goal'], 'advanced')
        self.assertTrue(view.legacy.isVisible())
        panel.project.make_plan.assert_not_called()
        panel.project.make_journey.assert_not_called()

    def test_selection_names_counts_and_dormant_delivery_remain_consistent(self):
        panel, view = self.panel, self.view
        view.goal_buttons['deliver'].click()
        panel.platform_checks['ios'].setChecked(True)
        panel.destination_checks['firebase'].setChecked(True)
        self.assertIn('iOS', view.config_tabs.tabToolTip(1))
        self.assertIn('Firebase', view.config_tabs.tabToolTip(2))
        self.assertFalse(view.config_tabs.tabIcon(1).isNull())
        before = panel.choices()
        view.config_tabs.setCurrentIndex(1)
        self.assertIs(view.config_tabs.currentWidget(), view.config_pages['platforms'])
        self.assertEqual(panel.choices(), before)
        panel.platform_checks['android'].setChecked(True)
        self.assertTrue(view.config_tabs.tabIcon(1).isNull())
        self.assertEqual(view.config_tabs.tabText(view.config_tabs.indexOf(view.config_pages['platforms'])), 'Platforms (2)')
        self.assertIn('(2)', view.config_tabs.tabToolTip(view.config_tabs.indexOf(view.config_pages['platforms'])))
        view.goal_buttons['validate'].click()
        self.assertEqual(view.config_tabs.tabText(2), 'Delivery (0)')
        self.assertFalse(view.config_tabs.isTabEnabled(2))
        self.assertTrue(panel.destination_checks['firebase'].isChecked())
        view.goal_buttons['deliver'].click()
        self.assertIn('Firebase', view.config_tabs.tabToolTip(2))
        view.config_tabs.setCurrentIndex(2)
        self.assertIs(view.config_tabs.currentWidget(), view.config_pages['delivery'])

    def test_presets_are_contextual_and_saving_does_not_reload_or_start_work(self):
        window, panel = self.window, self.panel
        self.window.show(); self.app.processEvents()
        panel.platform_checks['android'].setChecked(True)
        plan = integrated(self.root)
        panel.plan = plan
        panel.start.setEnabled(True)
        expected = panel.choices()
        with patch('build_manager.app.QInputDialog.getText', return_value=('Checks', True)):
            window.preset_actions['Save as new preset…'].trigger()
        self.flush_selections()
        self.assertIs(panel.plan, plan)
        self.assertEqual(window.saved_presets.currentText(), 'Checks')
        panel.platform_checks['ios'].setChecked(True)
        self.assertTrue(panel.preset_note.isVisible())
        self.assertEqual(panel.preset_note.text(), 'Overrides for this run')
        window.preset_actions['Reset overrides'].trigger()
        self.assertEqual(panel.choices(), expected)
        self.assertIsNone(panel.plan)
        self.assertEqual(window.saved_presets.currentText(), 'Checks')
        panel.stages.setCurrentIndex(1); self.app.processEvents()
        self.assertFalse(window.saved_presets.isVisible())
        panel.stages.setCurrentIndex(0); self.app.processEvents()
        self.assertTrue(window.saved_presets.isVisible())
        panel.project.make_plan.assert_not_called()
        panel.project.make_journey.assert_not_called()

    def test_single_section_navigation_tracks_buttons_cards_and_goal_changes(self):
        view, panel = self.view, self.panel
        self.window.show(); self.app.processEvents()
        self.assertTrue(view.config_tabs.tabBar().isVisible())
        self.assertEqual(view.goal.itemText(view.goal.findData('advanced')), 'Project operation')
        self.assertEqual(view.config_tabs.tabText(3), 'Options')
        for index, key in enumerate(view.config_pages):
            if key == 'delivery':
                view.choose_goal('deliver')
            before = panel.choices()
            bar = view.config_tabs.tabBar()
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
            self.assertIs(view.config_tabs.currentWidget(), view.config_pages[key])
            self.assertEqual(panel.choices(), before)
        view.open_proposed_card('source')
        self.assertEqual(view.config_tabs.currentIndex(), 0)
        view.open_section('delivery')
        view.choose_goal('validate')
        self.assertFalse(view.config_tabs.isTabEnabled(2))
        selected = next(name for name, page in view.config_pages.items() if page is view.config_tabs.currentWidget())
        self.assertNotEqual(selected, 'delivery')
        view.choose_goal('advanced')
        self.assertEqual(view.config_tabs.currentIndex(), 1)
        panel.project.make_plan.assert_not_called()
        panel.project.make_journey.assert_not_called()

    def test_project_suggestion_uses_its_exact_operation_and_can_only_be_copied(self):
        suggestion = dict(platform='example', operation='Package', backend='Local fixture', suite='package-checks')
        self.suggestions['Package with checks'] = suggestion
        window = ManagerWindow(self.window.registry)
        self.addCleanup(window.close)
        panel = window.panel
        panel.preset.setCurrentText('Package with checks')
        self.assertEqual(panel.choices()['goal'], 'advanced')
        self.assertEqual({key: panel.choices()[key] for key in suggestion}, suggestion)
        self.assertEqual(panel.configuration.preset_work_type.text(), 'Project operation')
        self.assertTrue(panel.goal.isHidden())
        self.assertFalse(window.preset_actions['Save changes to selected preset…'].isEnabled())
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        panel.configuration.override_goal.click()
        self.assertFalse(panel.goal.isHidden())
        panel.goal.setCurrentIndex(panel.goal.findData('build'))
        panel.goal.activated.emit(panel.goal.currentIndex())
        self.assertFalse(panel.preset_note.isHidden())
        window.preset_actions['Reset overrides'].trigger()
        self.assertTrue(panel.preset_note.isHidden())
        self.assertEqual({key: panel.choices()[key] for key in suggestion}, suggestion)
        with patch('build_manager.app.QInputDialog.getText', return_value=('Package with checks', True)):
            window.preset_actions['Save as new preset…'].trigger()
        self.flush_selections(window)
        self.assertEqual(panel.project.workflow_presets['Package with checks'], suggestion)
        self.assertTrue(window.preset_actions['Delete preset'].isEnabled())
        panel.preset.setCurrentIndex(panel.preset.count() - 1)
        self.assertEqual(panel.preset.currentText(), 'Package with checks')
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        panel.project.make_plan.assert_not_called()
        panel.project.make_journey.assert_not_called()

    def test_busy_state_locks_new_controls_and_project_switch_isolates_presets(self):
        panel, window = self.panel, self.window
        with patch('build_manager.app.QInputDialog.getText', return_value=('Only one', True)):
            window.preset_actions['Save as new preset…'].trigger()
        self.flush_selections()
        panel.set_busy(True)
        self.assertFalse(self.view.goal.isEnabled())
        self.assertFalse(window.saved_presets.isEnabled())
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        self.assertFalse(window.more.isEnabled())
        panel.set_busy(False)
        self.assertTrue(window.preset_actions['Delete preset'].isEnabled())
        window.projects.setCurrentIndex(1)
        self.assertEqual(window.saved_presets.count(), 1)
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        self.assertTrue(window.more.isEnabled())

    def test_sibling_preset_edit_keeps_existing_run_overrides_until_reselected(self):
        window, panel = self.window, self.panel
        with patch('build_manager.app.QInputDialog.getText', return_value=('Checks', True)):
            window.preset_actions['Save as new preset…'].trigger()
        sibling = window.run_workspace.add_view(panel.project_key)
        sibling.revision.setText('HEAD')
        with patch('build_manager.presets_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            sibling.preset_actions['Save changes to selected preset…'].trigger()
        self.flush_selections()
        self.assertEqual(panel.revision.text(), 'working-tree')
        self.assertFalse(panel.preset_actions['Delete preset'].isEnabled())
        self.assertIn('Saved choices changed', panel.preset.toolTip())
        panel.preset.activated.emit(panel.preset.currentIndex())
        self.assertEqual(panel.revision.text(), 'HEAD')
        self.assertTrue(panel.preset_actions['Delete preset'].isEnabled())

    def flush_selections(self, window=None):
        window = window or self.window
        for _ in range(200):
            if window.selection_store.flush() and not window.selection_store.callbacks:
                return
            QTest.qWait(10)
        self.fail('Remembered selections and preset writes did not settle.')

    def test_long_selection_labels_keep_header_and_footer_inside_laptop_window(self):
        window, panel = self.window, self.panel
        for control in (*panel.platform_checks.values(), *panel.destination_checks.values()):
            control.setText(control.text() + ' extended project destination identity' * 3)
            control.setChecked(True)
        self.view.goal_buttons['deliver'].click()
        original = QFont(self.app.font())
        self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        window.resize(1024, 700); window.show()
        for _ in range(5): self.app.processEvents()
        self.assertEqual((window.width(), window.height()), (1024, 700))
        bar = self.view.config_tabs.tabBar()
        self.assertTrue(bar.isVisible())
        for index in range(bar.count()):
            self.assertNotIn('extended project destination', bar.tabText(index))
        self.assertIn('extended project destination', bar.tabToolTip(1))
        self.assertTrue(window.rect().contains(bar.rect().translated(bar.mapTo(window, QPoint()))))
        self.assertTrue(window.rect().contains(panel.prepare.rect().translated(panel.prepare.mapTo(window, QPoint()))))


if __name__ == '__main__':
    unittest.main()
