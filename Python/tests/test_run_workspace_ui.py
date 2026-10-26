"""Independent run documents use the pinned commonUtils docking lifecycle."""
import json
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem
import test_toolbar_goals_ui as fixture
from test_journeys import integrated


class RunWorkspaceTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ToolbarGoalTests.setUpClass.__func__)
    setUp = fixture.ToolbarGoalTests.setUp

    def pump(self):
        for _ in range(5):
            self.app.processEvents()

    def test_last_attached_run_cannot_detach_and_tabs_keep_independent_state(self):
        window, first = self.window, self.panel
        window.show()
        self.pump()
        workspace = window.run_workspace
        dock = workspace.docks[0]
        self.assertFalse(workspace.can_move_tab(dock))
        self.assertIsNone(workspace.detach_dock(dock))
        first.revision.setText('first-branch')
        first.run_view.reset(integrated(self.root))
        second = workspace.request_new_view()
        self.assertIs(window.panel, second)
        self.assertIsNot(first.session, second.session)
        second.revision.setText('second-branch')
        self.assertEqual(first.revision.text(), 'first-branch')
        self.assertIsNotNone(first.run_view.plan)
        self.assertIsNone(second.run_view.plan)
        self.assertTrue(workspace.can_move_tab(dock))
        detached = workspace.detach_dock(dock)
        self.assertIsNotNone(detached)
        self.pump()
        self.assertIs(first.action_footer.parentWidget(), first)
        self.assertTrue(detached.isAncestorOf(first.action_footer))
        self.assertFalse(workspace.can_move_tab(workspace.docks[0]))
        self.assertTrue(detached.workspace.return_to_main(dock))
        self.pump()
        self.assertEqual(len(workspace.docks), 2)
        workspace._activate(dock)
        self.assertIs(window.panel, first)
        self.assertIs(window.saved_presets, first.saved_presets)

    def test_history_opens_another_tab_without_changing_the_draft(self):
        window, first = self.window, self.panel
        plan = integrated(self.root)
        directory = self.root / 'retained'
        directory.mkdir()
        plan.save(directory / 'plan.json')
        result = directory / 'result.json'
        result.write_text(json.dumps(dict(schema=1, status='passed', phases=[], plan_identity=plan.identity)))
        item = QTreeWidgetItem(['Retained result'])
        item.setData(0, Qt.ItemDataRole.UserRole, str(result))
        first.history.addTopLevelItem(item)
        first.revision.setText('keep-this-draft')
        first.open_history(item)
        self.assertEqual(len(window.run_workspace.docks), 2)
        self.assertIsNone(first.result)
        self.assertEqual(first.revision.text(), 'keep-this-draft')
        self.assertEqual(window.panel.result, result)
        self.assertEqual(window.panel.stages.currentIndex(), 2)
        self.assertEqual(window.panel.stage_tabs.currentIndex(), 2)
        self.assertEqual(window.panel.run_view.outcome, 'passed')

    def test_background_busy_tab_does_not_block_other_tabs_project_choices_or_close_safety(self):
        window, first = self.window, self.panel
        second = window.run_workspace.request_new_view()
        first.set_busy(True)
        self.assertTrue(window.projects.isEnabled())
        self.assertFalse(first.projects.isEnabled())
        self.assertIs(window.panel, second)
        self.assertFalse(first.prepare_close())
        with patch('build_manager.app.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            self.assertFalse(window.close())
        self.assertFalse(first.closing)
        first.set_busy(False)
        self.assertTrue(window.projects.isEnabled())

    def test_closing_active_detached_run_restores_main_window_actions(self):
        window, first = self.window, self.panel
        workspace = window.run_workspace
        workspace.request_new_view()
        detached = workspace.detach_dock(workspace.docks[1])
        self.pump()
        detached.workspace._activate(detached.workspace.docks[0])
        self.assertIsNot(window.panel, first)
        self.assertTrue(detached.close())
        self.pump()
        self.assertIs(window.panel, first)
        self.assertIs(window.saved_presets, first.saved_presets)
        self.assertEqual(len(workspace.all_docks), 1)

    def test_closing_window_retires_detached_runs(self):
        window = self.window
        workspace = window.run_workspace
        second = workspace.request_new_view()
        detached = workspace.detach_dock(workspace.docks[1])
        self.pump()
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.assertTrue(window.close())
        self.pump()
        self.assertTrue(second.closing)
        from shiboken6 import isValid
        self.assertTrue(not isValid(detached) or not detached.isVisible())

    def test_tabs_own_project_controls_and_project_change_preserves_siblings(self):
        window, first = self.window, self.panel
        window.show()
        first.revision.setText('preserve-first-draft')
        first.run_view.reset(integrated(self.root))
        workspace = window.run_workspace
        first_dock = workspace.docks[0]
        second = workspace.request_new_view()
        second_dock = next(dock for dock in workspace.docks if dock.widget() is second)
        for panel in (first, second):
            for control in (panel.projects, panel.project_settings, panel.more, panel.help_button):
                self.assertTrue(panel.isAncestorOf(control))
        second.projects.setCurrentIndex(second.projects.findData('two'))
        changed = second_dock.widget()
        self.assertIsNot(changed, second)
        self.assertIs(window.panel, changed)
        self.assertEqual(changed.project_key, 'two')
        self.assertEqual(first.project_key, 'one')
        self.assertEqual(first.revision.text(), 'preserve-first-draft')
        self.assertIsNotNone(first.run_view.plan)
        self.assertIsNone(changed.run_view.plan)
        self.assertEqual(len(workspace.docks), 2)
        self.assertIs(workspace.docks[0], first_dock)
        self.assertIs(first_dock.widget(), first)
        self.assertIn('two', second_dock.windowTitle())
        first_dock.raise_()
        self.pump()
        workspace._activate(first_dock)
        self.assertIs(window.projects, first.projects)
        self.assertEqual(window.projects.currentData(), 'one')
        with patch.object(first, 'edit_settings') as first_settings, patch.object(changed, 'edit_settings') as other_settings:
            second_dock.raise_()
            self.pump()
            workspace._activate(second_dock)
            first.project_settings.click()
            first_settings.assert_called_once()
            other_settings.assert_not_called()
        with patch.object(first, 'verify_settings') as first_verify, patch.object(changed, 'verify_settings') as other_verify:
            first.menu_actions['Check connections and settings…'].trigger()
            first_verify.assert_called_once()
            other_verify.assert_not_called()

    def test_detached_tab_keeps_toolbar_and_new_tabs_use_its_project(self):
        window, first = self.window, self.panel
        workspace = window.run_workspace
        second = workspace.request_new_view()
        second.projects.setCurrentIndex(second.projects.findData('two'))
        dock = next(dock for dock in workspace.docks if dock.widget().project_key == 'two')
        detached = workspace.detach_dock(dock)
        self.pump()
        second = dock.widget()
        self.assertTrue(detached.isAncestorOf(second.projects))
        workspace._activate(workspace.docks[0])
        third = detached.workspace.request_new_view()
        self.assertEqual(third.project_key, 'two')
        self.assertEqual(first.project_key, 'one')
        second.projects.setCurrentIndex(second.projects.findData('one'))
        self.assertIs(dock.workspace, detached.workspace)
        self.assertEqual(dock.widget().project_key, 'one')
        self.assertEqual(third.project_key, 'two')
        self.assertTrue(detached.isAncestorOf(dock.widget().help_button))
        self.pump()
        self.assertIsNot(first, dock.widget())

    def test_busy_project_is_locked_while_an_idle_tab_can_change_project(self):
        window, first = self.window, self.panel
        second = window.run_workspace.request_new_view()
        dock = next(dock for dock in window.run_workspace.docks if dock.widget() is second)
        first.set_busy(True)
        self.addCleanup(lambda: first.set_busy(False))
        self.assertFalse(first.projects.isEnabled())
        self.assertTrue(second.projects.isEnabled())
        second.projects.setCurrentIndex(second.projects.findData('two'))
        self.assertTrue(first.is_busy)
        self.assertEqual(first.project_key, 'one')
        self.assertEqual(dock.widget().project_key, 'two')
        self.assertTrue(dock.widget().more.isEnabled())
        first.projects.setCurrentIndex(first.projects.findData('two'))
        self.assertEqual(first.projects.currentData(), 'one')
        self.assertIs(window.run_workspace.docks[0].widget(), first)

    def test_failed_project_change_keeps_original_tab_and_draft(self):
        window, first = self.window, self.panel
        first.revision.setText('preserve-on-error')
        first.plan = integrated(self.root)
        with patch('build_manager.app.ProjectBridge', side_effect=ValueError('Project unavailable')):
            first.projects.setCurrentIndex(first.projects.findData('two'))
        self.assertIs(window.panel, first)
        self.assertEqual(first.project_key, 'one')
        self.assertEqual(first.projects.currentData(), 'one')
        self.assertEqual(first.revision.text(), 'preserve-on-error')
        self.assertIsNotNone(first.plan)
        self.assertIn('Project unavailable', first.status.text())

    def test_refreshing_registry_does_not_replace_other_tabs(self):
        first = self.panel
        second = self.window.run_workspace.request_new_view()
        second.projects.setCurrentIndex(second.projects.findData('two'))
        second = self.window.panel
        first.revision.setText('first-draft')
        second.revision.setText('second-draft')
        self.window.refresh()
        self.assertEqual(first.revision.text(), 'first-draft')
        self.assertEqual(second.revision.text(), 'second-draft')
        self.assertEqual((first.project_key, second.project_key), ('one', 'two'))

    def test_saved_settings_invalidate_only_tabs_for_the_same_project(self):
        window, first = self.window, self.panel
        same = window.run_workspace.request_new_view()
        other = window.run_workspace.request_new_view()
        other.projects.setCurrentIndex(other.projects.findData('two'))
        other = window.panel
        same.plan = integrated(self.root)
        other.plan = integrated(self.root)
        expected = other.plan
        window.project_settings_saved(first)
        self.assertIsNone(same.plan)
        self.assertIs(other.plan, expected)
        self.assertIn('Project settings saved', first.status.text())

    def test_empty_tab_after_registration_removal_does_not_change_siblings(self):
        window, first = self.window, self.panel
        second = window.run_workspace.request_new_view()
        second.projects.setCurrentIndex(second.projects.findData('two'))
        second = window.panel
        dock = next(dock for dock in window.run_workspace.docks if dock.widget() is second)
        first.revision.setText('keep-existing-project')
        self.data['projects'].pop('two')
        self.data['selected'] = 'one'
        window.refresh(view=second, selected=None)
        self.assertIsNone(dock.widget().project)
        self.assertIsNone(dock.widget().project_key)
        self.assertFalse(dock.widget().project_settings.isEnabled())
        self.assertEqual(first.project_key, 'one')
        self.assertEqual(first.revision.text(), 'keep-existing-project')
        dock.widget().projects.setCurrentIndex(0)
        self.assertEqual(dock.widget().project_key, 'one')
        self.assertEqual(len(window.run_workspace.docks), 2)

    def test_unavailable_initial_project_still_opens_tab_scoped_recovery_controls(self):
        from build_manager.app import ManagerWindow
        with patch('build_manager.app.ProjectBridge', side_effect=ValueError('Checkout unavailable')):
            failed = ManagerWindow(self.window.registry)
        self.addCleanup(failed.close)
        self.assertIsNone(failed.panel)
        self.assertEqual(failed.current_view.project_key, 'one')
        self.assertTrue(failed.current_view.isAncestorOf(failed.projects))
        self.assertIn('Checkout unavailable', failed.setup_summary.text())
        self.assertFalse(failed.project_settings.isEnabled())
        self.assertTrue(failed.menu_actions['Locate moved checkout…'].isEnabled())
