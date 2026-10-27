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
from PySide6.QtWidgets import QApplication

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
        self.data = dict(projects={key: dict(name=key, root=str(self.root / key), presets={})
            for key in ('one', 'two')}, selected='one')
        owner = self
        class Store:
            def read(self): return deepcopy(owner.data)
            def select(self, key): owner.data['selected'] = key
            def resolve(self, key):
                return owner.data['projects'][key], dict(name=key, interpreter=OtherProject.interpreter)
            def selections(self, key, choices): owner.data['projects'][key]['selections'] = choices
            def save_preset(self, key, name, choices):
                Registry.validate_selections(choices)
                owner.data['projects'][key]['presets'][name.strip()] = deepcopy(choices)
            def delete_preset(self, key, name): owner.data['projects'][key]['presets'].pop(name)
        def bridge(store, key):
            project = OtherProject(self.root)
            project.journey_capability = deepcopy(CAPABILITY)
            project.journey_capability['platforms']['ios']['label'] = 'iOS'
            project.row = deepcopy(self.data['projects'][key])
            project.make_plan = Mock(side_effect=AssertionError('Intent must not start planning'))
            project.make_journey = Mock(side_effect=AssertionError('Intent must not start planning'))
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
        self.assertEqual(window.controls.count(), 4)
        self.assertEqual(window.projects.currentText(), 'one')
        self.assertEqual(window.projects.toolTip(), str(self.root / 'one'))
        self.assertEqual(set(window.menu_actions), {'Add project…', 'Locate moved checkout…',
            'Remove registration', 'Accounts…', 'Test machines…', 'Check connections and settings…',
            'Clean up builds…', 'App settings…'})
        self.assertFalse(window.menu_actions['Clean up builds…'].isEnabled())
        self.assertIs(window.controls.itemAt(3).widget(), window.help_button)
        self.data['projects']['two']['name'] = 'one'
        window.refresh()
        self.assertNotEqual(window.projects.itemText(0), window.projects.itemText(1))

    def test_visible_goals_share_existing_selection_and_keyboard_invalidation(self):
        panel, view = self.panel, self.view
        panel.plan = integrated(self.root)
        panel.start.setEnabled(True)
        self.window.show(); self.app.processEvents()
        view.goal_buttons['deliver'].setFocus()
        QTest.keyClick(view.goal_buttons['deliver'], Qt.Key.Key_Space)
        self.assertEqual(panel.choices()['goal'], 'deliver')
        self.assertIsNone(panel.plan)
        self.assertFalse(panel.start.isEnabled())
        self.assertTrue(view.goal_buttons['deliver'].isChecked())
        self.assertFalse(view.goal_buttons['validate'].isChecked())
        view.goal_buttons['advanced'].click()
        self.assertTrue(view.goal_buttons['advanced'].isChecked())
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
        self.assertEqual(view.config_tabs.tabText(view.config_tabs.indexOf(view.config_pages['platforms'])), 'Test (2)')
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
            window.preset_actions['Save preset…'].trigger()
        self.assertIs(panel.plan, plan)
        self.assertEqual(window.saved_presets.currentText(), 'Checks')
        panel.platform_checks['ios'].setChecked(True)
        self.assertIn('Modified', window.saved_presets.currentText())
        window.saved_presets.activated.emit(window.saved_presets.currentIndex())
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
        self.assertEqual(view.goal_buttons['advanced'].text(), 'Project operation…')
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

    def test_busy_state_locks_new_controls_and_project_switch_isolates_presets(self):
        panel, window = self.panel, self.window
        with patch('build_manager.app.QInputDialog.getText', return_value=('Only one', True)):
            window.preset_actions['Save preset…'].trigger()
        panel.set_busy(True)
        self.assertTrue(all(not button.isEnabled() for button in self.view.goal_buttons.values()))
        self.assertFalse(window.saved_presets.isEnabled())
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        self.assertFalse(window.more.isEnabled())
        panel.set_busy(False)
        self.assertTrue(window.preset_actions['Delete preset'].isEnabled())
        window.projects.setCurrentIndex(1)
        self.assertEqual(window.saved_presets.count(), 1)
        self.assertFalse(window.preset_actions['Delete preset'].isEnabled())
        self.assertTrue(window.more.isEnabled())

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
