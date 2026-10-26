"""Full-window action reachability and direct, evidence-preserving attention routes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFrame

from build_manager.app import ManagerWindow
from build_manager.run_ui import RunView
from build_manager.ui import EffectReviewDialog, ManagerPanel
from test_journeys import CAPABILITY, integrated
from test_ui import OtherProject


class ActionHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = integrated(self.root)

    def project(self):
        project = OtherProject(self.root)
        project.journey_capability = deepcopy(CAPABILITY)
        project.row = dict(trusted=True, selections={})
        return project

    def window(self):
        project = self.project()
        class Registry:
            def read(self):
                return dict(projects={key: dict(name=key, root=str(project.root))
                    for key in ('one', 'two')}, selected='one')
            def select(self, *_): pass
            def selections(self, *_): pass
            def resolve(self, *_):
                return dict(root=str(project.root)), dict(name='Fixture', interpreter=project.interpreter)
        factory = patch('build_manager.app.ProjectBridge', return_value=project)
        factory.start()
        self.addCleanup(factory.stop)
        window = ManagerWindow(Registry())
        self.addCleanup(window.close)
        return window

    def view(self):
        view = RunView()
        self.addCleanup(view.close)
        view.reset(self.plan)
        return view

    def test_full_window_footer_stays_outside_scroll_at_laptop_sizes_and_larger_text(self):
        window = self.window()
        panel = window.panel
        panel.present_plan(self.plan)
        panel.start.setEnabled(True)
        panel.run_view.reset(self.plan)
        panel.run_view.update_phase(dict(id='ios', status='failed', error='Fixture failure'))
        panel.run_view.complete(dict(status='failed'))
        original = QFont(self.app.font())
        self.addCleanup(self.app.setFont, original)
        for size, point_size in (((1280, 800), original.pointSize()), ((1024, 700), 14)):
            font = QFont(original)
            font.setPointSize(point_size)
            self.app.setFont(font)
            window.resize(*size)
            window.show()
            for stage, button in enumerate((panel.prepare, panel.start, panel.run_problems, panel.view_history_button)):
                panel.stages.setCurrentIndex(stage)
                for _ in range(4): self.app.processEvents()
                self.assertEqual((window.width(), window.height()), size)
                self.assertFalse(window.scroll.isAncestorOf(panel.action_footer))
                self.assertTrue(button.isVisible())
                for value in (0, window.scroll.verticalScrollBar().maximum()):
                    window.scroll.verticalScrollBar().setValue(value)
                    self.app.processEvents()
                    rect = button.rect().translated(button.mapTo(window, QPoint()))
                    self.assertTrue(window.rect().contains(rect), (size, stage, rect))
                self.assertEqual(button.property('actionRole'), 'primary')
        panel.stages.setCurrentIndex(2)
        panel.set_busy(True)
        self.assertTrue(panel.cancel.isVisible())
        self.assertTrue(panel.cancel.isEnabled())
        self.assertEqual(panel.cancel.property('actionRole'), 'secondary')
        panel.set_busy(False)

    def test_switching_project_retires_its_docked_footer(self):
        window = self.window()
        window.show()
        previous = window.panel.action_footer
        window.projects.setCurrentIndex(1)
        self.app.processEvents()
        self.assertFalse(previous.isVisible())
        self.assertIsNot(window.panel.action_footer, previous)
        self.assertIs(window.panel.action_footer.parentWidget(), window)
        self.assertEqual([frame for frame in window.findChildren(QFrame, 'actionFooter') if frame.isVisible()],
                         [window.panel.action_footer])

    def test_failure_without_case_reports_opens_failed_step_directly(self):
        view = self.view()
        view.update_phase(dict(id='ios', status='failed', error='Simulator check failed'))
        view.inspect_summary_phase('android')
        view.attention_problems.click()
        self.assertEqual(view.selected, 'ios')
        self.assertEqual(view.pages.currentIndex(), 1)
        self.assertIs(view.tabs.currentWidget(), view.steps.parentWidget())
        self.assertIn('Simulator check failed', view.detail.toPlainText())

    def test_problem_tests_clear_unrelated_selection_and_search(self):
        view = self.view()
        view.update_phase(dict(id='ios', status='failed', tests=[dict(name='broken', status='failed',
            suite='fixture', classname='', seconds=1, message='Expected success')]))
        view.inspect_summary_phase('android')
        view.search.setText('unrelated')
        view.attention_problems.click()
        self.assertEqual(view.selected, '')
        self.assertEqual(view.search.text(), '')
        self.assertEqual(view.filter.currentText(), 'Problems')
        self.assertIs(view.tabs.currentWidget(), view.tests.parentWidget())
        self.assertFalse(view.tests.topLevelItem(0).isHidden())

    def test_mixed_failure_and_approval_requires_available_retained_review(self):
        panel = ManagerPanel(self.project())
        self.addCleanup(panel.close)
        panel.run_view.reset(self.plan)
        panel.stages.setCurrentIndex(2)
        panel.run_view.update_phase(dict(id='ios', status='failed'))
        panel.run_view.update_phase(dict(id='firebase', status='awaiting_review'))
        panel.result = self.root / 'result.json'
        panel.set_busy(True)
        with patch.object(panel, 'resume_workflow') as resume:
            self.assertFalse(panel.run_view.attention_review.isEnabled())
            panel.run_view.attention_review.click()
            resume.assert_not_called()
            panel.resumable = True
            panel.set_busy(False)
            panel.run_view.complete(dict(status='awaiting_review'))
            self.assertIn('failed step', panel.run_view.attention_title.text())
            self.assertIn('waiting for approval', panel.run_view.attention_title.text())
            self.assertEqual(panel.continue_run.property('actionRole'), 'primary')
            self.assertEqual(panel.run_problems.property('actionRole'), 'secondary')
            panel.run_view.attention_review.click()
            resume.assert_called_once_with(panel.result)

    def test_unknown_outcome_takes_priority_and_reset_clears_attention(self):
        view = self.view()
        view.update_phase(dict(id='ios', status='failed'))
        view.update_phase(dict(id='firebase', status='unknown', reason='Provider receipt missing'))
        view.attention_problems.click()
        self.assertEqual(view.selected, 'firebase')
        self.assertIn('Provider receipt missing', view.detail.toPlainText())
        self.assertIn('Unknown outcome', view.attention_title.text())
        view.reset(self.plan)
        self.assertTrue(view.attention.isHidden())
        self.assertFalse(view.attention_review.isEnabled())
        self.assertFalse(view.has_problems())

    def test_approval_styling_keeps_cancel_default_and_choices_unselected(self):
        dialog = EffectReviewDialog('Fixture retained evidence', steps=('firebase',))
        self.addCleanup(dialog.close)
        buttons = dialog.findChild(QDialogButtonBox)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        approve = next(button for button in buttons.buttons() if button is not cancel)
        self.assertTrue(cancel.isDefault())
        self.assertFalse(approve.autoDefault())
        self.assertFalse(approve.isEnabled())
        self.assertEqual(approve.property('actionRole'), 'primary')
        dialog.approvals['firebase'].setChecked(True)
        self.assertTrue(approve.isEnabled())


if __name__ == '__main__':
    unittest.main()
