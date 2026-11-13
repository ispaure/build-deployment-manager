"""Project onboarding, searchable settings and a review that explains effects."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from build_manager import Phase,Plan
from build_manager.app import ManagerWindow
from build_manager.project_setup_ui import AddProjectDialog
from build_manager.registry import Registry
from build_manager.settings_ui import SettingsDialog
from build_manager.ui import ManagerPanel
from build_manager.run_ui import RunView
from test_ui import OtherProject


class OnboardingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def wait(self,dialog):
        deadline=time.monotonic()+5
        while dialog.busy:
            self.app.processEvents();time.sleep(.005)
            self.assertLess(time.monotonic(),deadline)

    def descriptor(self,root,name):
        root.mkdir()
        (root/'build-project.json').write_text(json.dumps(dict(schema=1,adapter_api=1,project_id=name,name=name,
            interpreter='.venv/bin/python',bridge='bridge.py',capabilities=dict(platforms=['native'],operations=['Check']))))
        marker=root/'adapter-executed'
        (root/'bridge.py').write_text(f'from pathlib import Path;Path({str(marker)!r}).touch()')
        return marker

    def test_add_preview_validates_folder_and_does_not_execute_project_tools(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)/'project';marker=self.descriptor(root,'example')
            dialog=AddProjectDialog()
            dialog.path.setText(folder);dialog.preview()
            self.assertFalse(dialog.add_button.isEnabled());self.assertIn('not ready',dialog.summary.text())
            dialog.path.setText(str(root));dialog.preview()
            self.assertTrue(dialog.add_button.isEnabled());self.assertIn('environment is missing',dialog.summary.text())
            self.assertEqual(dialog.root,root.resolve());self.assertFalse(marker.exists())
            dialog.reject()

    def test_add_selects_the_new_project_and_empty_actions_have_no_silent_noops(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);registry=Registry(root/'private');window=ManagerWindow(registry)
            try:
                self.assertFalse(window.project_settings.isEnabled())
                for name in ('one','two'):
                    project=root/name;self.descriptor(project,name)
                    with patch('build_manager.project_setup_ui.AddProjectDialog') as chooser:
                        chooser.return_value.exec.return_value=1;chooser.return_value.root=project
                        chooser.return_value.registration_name.text.return_value = ''
                        window.add()
                    self.assertEqual(window.panel.project.root,project.resolve())
                    self.assertEqual(registry.resolve()[0]['project_id'],name)
                self.assertEqual(window.projects.count(),2)
                self.assertTrue(window.menu_actions['Manage build storage…'].isEnabled())
            finally:window.close();self.app.processEvents()

    def test_settings_search_preserves_edits_and_filters_categories_and_sources(self):
        class Project:
            def settings_view(self):
                return {'tools.python':dict(value='original',section='Tools',label='Desktop Python'),
                    'delivery.group':dict(value='testers',section='Delivery',label='Tester group')}
        dialog=SettingsDialog(Project());dialog.show();self.wait(dialog)
        try:
            dialog.controls['tools.python'].setText('changed')
            dialog.search.setText('desktop python');self.app.processEvents()
            self.assertTrue(dialog.sidebar.topLevelItem(1).isHidden())
            self.assertIn('Unsaved changes',dialog.status.text())
            self.assertEqual(dialog.origins[0].text(), 'Unsaved checkout edit')
            dialog.show_origins.setChecked(False)
            self.assertTrue(all(label.isHidden() for label in dialog.origins))
            dialog.search.setText('no matches');self.assertFalse(dialog.search_hint.isHidden())
            dialog.search.clear();self.assertEqual(dialog.controls['tools.python'].text(),'changed')
            dialog.show_origins.setChecked(True)
            self.assertFalse(dialog.origins[0].isHidden())
            self.assertTrue(dialog.origins[1].isHidden())
        finally:
            dialog.dirty=False;dialog.reject();self.app.processEvents()

    def test_review_lists_steps_without_opening_technical_details_and_names_effects(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);panel=ManagerPanel(OtherProject(root))
            try:
                plan=Plan('Example','Prepare',{'dirty':True,'fingerprint':'exact-capture'},
                    (Phase('portable-contracts',('python','-V'),folder,effect='test'),
                     Phase('send',('python','-V'),folder,effect='upload',dependencies=('portable-contracts',))),str(root/'work'))
                panel.present_plan(plan);panel.stages.setCurrentIndex(1);panel.show();self.app.processEvents()
                self.assertFalse(panel.review_flow.isHidden())
                self.assertEqual(len(panel.review_flow.canvas.cards), 2)
                self.assertEqual(panel.review_flow.canvas.edges, [('portable-contracts', 'send')])
                self.assertEqual(panel.review_board.topLevelItemCount(),2)
                self.assertIn('separate approval',panel.review_board.topLevelItem(1).text(2))
                self.assertIn('uncommitted changes',panel.review_summary.text())
                self.assertIn('uploads requiring review',panel.review_summary.text())
            finally:panel.close();self.app.processEvents()

    def test_unreported_counts_are_unavailable_and_unknown_effects_require_reconciliation(self):
        with TemporaryDirectory() as folder:
            view=RunView();plan=OtherProject(Path(folder)).make_plan()
            view.reset(plan)
            self.assertIn('—',view.count_cards['passed'][0].text())
            self.assertFalse(view.problems_button.isEnabled())
            view.complete(dict(status='unknown',seconds=1))
            self.assertIn('provider status',view.next_action.text())
            view.close()

    def test_command_project_registers_without_python_bridge_and_disables_unsupported_actions(self):
        from build_manager.onboarding import scaffold
        from build_manager.preparation import preparation_request
        import sys
        with TemporaryDirectory() as folder:
            root = Path(folder)
            scaffold(root, 'Commands', 'org.example.commands', [sys.executable, '-c', "print('fixture')"])
            dialog = AddProjectDialog()
            dialog.path.setText(str(root)); dialog.preview()
            self.assertTrue(dialog.add_button.isEnabled())
            self.assertIn('no Python bridge required', dialog.summary.text())
            dialog.reject()
            registry = Registry(root / 'registry'); registry.add(root)
            window = ManagerWindow(registry)
            try:
                self.assertEqual(window.projects.currentText(), 'Commands')
                self.assertNotIn('Project tooling…', window.menu_actions)
                self.assertFalse(window.menu_actions['Check connections and settings…'].isEnabled())
                self.assertTrue(window.menu_actions['Manage build storage…'].isEnabled())
                # Manager-owned retained runs are available without adapter storage actions.
                with patch('build_manager.storage_ui.StorageDialog') as storage_dialog:
                    window.menu_actions['Manage build storage…'].trigger()
                    storage_dialog.assert_called_once_with(window.panel.project, window.panel)
                    storage_dialog.return_value.exec.assert_called_once()
                plan = preparation_request(window.panel.configuration.selection()).prepare(window.panel.project)
                self.assertEqual(plan.operation, 'Check')
            finally:
                window.close(); self.app.processEvents()

    def test_missing_bridge_is_visible_before_any_adapter_execution(self):
        with TemporaryDirectory() as folder:
            root = Path(folder) / 'project'
            self.descriptor(root, 'missing bridge')
            (root / 'bridge.py').unlink()
            dialog = AddProjectDialog()
            dialog.path.setText(str(root)); dialog.preview()
            self.assertIn('bridge', dialog.summary.text())
            self.assertTrue(dialog.add_button.isEnabled())
            dialog.reject()
