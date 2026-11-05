"""Direct repairs and readable, navigable maps without changing executable work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
import sys
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, Qt, QRect, QRectF, qVersion
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from build_manager import Phase, Plan
from build_manager.ui import ManagerPanel
from build_manager.run_ui import RunView
from build_manager.workflow_ui import WorkflowGraphView
import test_toolbar_goals_ui as toolbar_fixtures
import test_recipient_ui as recipient_fixtures
from test_journeys import integrated


class BlockerCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = toolbar_fixtures.ToolbarGoalTests()
        self.fixture.app = self.app
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window, self.panel = self.fixture.window, self.fixture.panel
        self.view, self.root = self.panel.configuration, self.fixture.root

    def test_missing_platform_action_focuses_exact_choice_without_selecting_it(self):
        panel, view = self.panel, self.view
        view.goal_buttons['deliver'].click()
        panel.platform_checks['ios'].setChecked(True)
        panel.destination_checks['firebase'].setChecked(True)
        before = panel.choices()
        self.window.show(); self.app.processEvents()
        button = view.blocker_actions['missing.android']
        button.setFocus(); QTest.keyClick(button, Qt.Key.Key_Space)
        self.assertIs(view.config_tabs.currentWidget(), view.config_pages['platforms'])
        self.assertTrue(panel.platform_checks['android'].hasFocus())
        self.assertEqual(view.proposed_flow.selected, 'missing.android')
        self.assertEqual(panel.choices(), before)
        panel.project.make_journey.assert_not_called()
        panel.platform_checks['android'].setChecked(True)
        self.assertNotIn('missing.android', view.blocker_actions)

    def test_source_repair_is_based_on_declared_requirements_and_retains_edits(self):
        panel, view = self.panel, self.view
        capability = panel.project.journey_capability
        capability['destinations']['firebase']['source_policy'] = 'committed'
        original = deepcopy(capability)
        view.goal_buttons['deliver'].click()
        panel.platform_checks['android'].setChecked(True)
        panel.destination_checks['firebase'].setChecked(True)
        self.window.show(); self.app.processEvents()
        before = panel.choices()
        self.assertEqual(view.proposed_flow.canvas.states['source'][0], 'needs_selection')
        view.blocker_actions['source'].click()
        self.assertTrue(view.source_mode.hasFocus())
        self.assertEqual(panel.choices(), before)
        view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
        self.assertNotIn('source', view.blocker_actions)
        self.assertEqual(capability, original)
        self.assertTrue(view.blocker_strip.isHidden())
        # An unspecified project policy is advisory, not a fabricated blocker.
        capability['destinations']['firebase'].pop('source_policy')
        view.source_mode.setCurrentIndex(view.source_mode.findData('working-tree'))
        self.assertNotIn('source', view.blocker_actions)

    def test_recipient_repair_focuses_picker_instead_of_earlier_notes(self):
        project = recipient_fixtures.RecipientUITests.project(None, self.root)
        project.run_fields.insert(0, dict(id='notes', label='Device notes', destinations=['phones']))
        project.make_journey = Mock(side_effect=AssertionError('Repair must not prepare a plan'))
        panel = ManagerPanel(project); self.addCleanup(panel.close)
        panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
        panel.platform_checks['android'].setChecked(True)
        panel.destination_checks['phones'].setChecked(True)
        panel.resize(1024, 700); panel.show(); self.app.processEvents()
        before = panel.choices()
        view = panel.configuration
        view.blocker_actions['recipients.phones'].click()
        picker = panel.run_fields.controls['phones']
        self.assertTrue(picker.items.hasFocus())
        self.assertTrue(view.delivery_categories['Mobile dev devices'][0].isAncestorOf(view.destination_checks['phones']))
        self.assertEqual(panel.choices(), before)
        project.make_journey.assert_not_called()
        picker.set_choices([dict(id='fixture-device', label='Fixture device')])
        picker.items.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertNotIn('recipients.phones', view.blocker_actions)

    def test_actions_wrap_at_laptop_size_and_lock_during_active_work(self):
        panel, view = self.panel, self.view
        panel.project.journey_capability['destinations']['firebase']['source_policy'] = 'committed'
        view.goal_buttons['deliver'].click()
        panel.destination_checks['firebase'].setChecked(True)
        panel.destination_checks['testflight'].setChecked(True)
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        self.window.resize(1024, 700); self.window.show()
        for _ in range(5): self.app.processEvents()
        self.assertEqual((self.window.width(), self.window.height()), (1024, 700))
        self.assertGreaterEqual(len(view.blocker_actions), 3)
        for button in view.blocker_actions.values():
            self.assertTrue(self.window.rect().contains(button.rect().translated(button.mapTo(self.window, QPoint()))))
        panel.set_busy(True)
        self.assertTrue(all(not button.isEnabled() for button in view.blocker_actions.values()))
        panel.set_busy(False)

    def long_plan(self):
        phases = []
        for index in range(12):
            phases.append(Phase(f'step-{index}', (sys.executable, '-V'), str(self.root),
                dependencies=(phases[-1].id,) if phases else (), label=f'Check suite {index + 1}',
                effect='upload' if index == 11 else 'test'))
        return Plan('Fixture', 'Inspect', {}, tuple(phases), str(self.root / 'workspace'))

    def test_fit_contains_complete_graph_and_keyboard_reveals_cards_after_zoom(self):
        plan = self.long_plan(); before = plan.data()
        flow = WorkflowGraphView(); self.addCleanup(flow.close)
        flow.resize(600, 500); flow.reset(plan, preview=True); flow.map_button.click(); flow.show()
        for _ in range(5): self.app.processEvents()
        self.assertEqual(flow.scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(flow.scroll.verticalScrollBar().maximum(), 0)
        flow.orientation.setCurrentIndex(flow.orientation.findData('horizontal'))
        flow.scroll.zoom(flow.scroll.maximum_scale / flow.scroll.transform().m11())
        self.assertGreater(flow.scroll.horizontalScrollBar().maximum(), 0)
        card = flow.canvas.cards['step-11'][0]
        card.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        rect = flow.scroll.mapFromScene(flow.scroll.proxy.mapRectToScene(QRectF(card.geometry()))).boundingRect()
        self.assertTrue(flow.scroll.viewport().rect().contains(rect))
        QTest.keyClick(card, Qt.Key.Key_Space)
        self.assertEqual(flow.selected, 'step-11')
        for _ in range(8): flow.scroll.zoom(.5)
        self.assertEqual(flow.scroll.transform().m11(), flow.scroll.minimum_scale)
        self.assertEqual(plan.data(), before)
        self.assertTrue(card.findChild(QLabel, 'approvalBadge').isVisible())
        flow.set_facts({'step-11': dict(status='passed')})
        self.assertTrue(card.findChild(QLabel, 'approvalBadge').isHidden())

    def test_status_updates_preserve_map_pan_and_manual_zoom(self):
        flow = WorkflowGraphView(); self.addCleanup(flow.close)
        flow.resize(600, 500); flow.reset(self.long_plan()); flow.map_button.click(); flow.show()
        flow.set_facts({'step-0': dict(status='running')})
        for _ in range(5): self.app.processEvents()
        bar = flow.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())
        before = bar.value()
        flow.set_facts({'step-0': dict(status='running')})
        for _ in range(5): self.app.processEvents()
        self.assertEqual(bar.value(), before)
        flow.set_facts({'step-0': dict(status='running'), 'step-11': dict(status='running')})
        for _ in range(5): self.app.processEvents()
        self.assertEqual(bar.value(), before)
        flow.scroll.zoom(1.2)
        scale = flow.scroll.transform().m11()
        flow.set_facts({'step-0': dict(status='running')})
        for _ in range(5): self.app.processEvents()
        self.assertEqual(flow.scroll.transform().m11(), scale)

    def test_blocked_card_and_exact_inspector_open_recorded_failed_prerequisite(self):
        plan = integrated(self.root); before = plan.data()
        view = RunView(); self.addCleanup(view.close)
        view.reset(plan)
        view.update_phase(dict(id='ios', status='failed', error='Synthetic gate failed'))
        view.inspect_summary_phase('firebase')
        self.assertEqual(view.blocking_key, 'ios')
        view.blocking_step.click()
        self.assertEqual(view.selected, 'ios')
        self.assertIn('Synthetic gate failed', view.detail.toPlainText())
        view.pages.setCurrentIndex(0)
        grouped = view.results_workspace.flow
        grouped.open_group('deliver.firebase')
        self.assertEqual(view.blocking_key, 'ios')
        view.blocking_step.click()
        self.assertEqual(view.pages.currentIndex(), 0)
        self.assertEqual(view.selected, 'ios')
        self.assertIs(view.tabs.currentWidget(), view.steps.parentWidget())
        self.assertEqual(plan.data(), before)

    def test_short_run_inspector_keeps_repair_visible_with_taller_font_metrics(self):
        splitter = self.panel.run_view.results_workspace.splitter
        # Fedora's substituted font leaves 23px less inspector height than
        # the local font. Recreate that bounded space at the same window size.
        with patch.object(splitter, 'fontMetrics', return_value=Mock(height=lambda: 32)):
            self.check_small_run_inspection(extra_summary_height=23)
            self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.check_task_row_visible()

    def test_fedora_height_inspector_keeps_repair_and_both_captions_inside_pane(self):
        view = self.panel.run_view.results_workspace
        # The recorded 129px details bound is a pane contract. Combining it
        # with independent ancestor pressure can exceed the native tree minimum.
        pane = view.sidebar_splitter.widget(1)
        pane.setParent(None)
        self.addCleanup(pane.close)
        pane.setFixedHeight(129)
        pane.resize(992, 129)
        pane.show()
        self.check_small_run_inspection()
        self.assertEqual(pane.size().toTuple(), (992, 129))
        self.check_inspector_captions_visible()

    def test_natural_run_inspector_keeps_repair_visible_with_43px_ancestor_pressure(self):
        view = self.panel.run_view.results_workspace
        with patch.object(view.splitter, 'fontMetrics', return_value=Mock(height=lambda: 32)):
            self.check_small_run_inspection(extra_summary_height=43)
        self.check_task_row_visible()
        self.check_inspector_captions_visible()

    def check_inspector_captions_visible(self):
        view = self.panel.run_view.results_workspace
        self.assertEqual(view.scope_label.accessibleName(), 'Evidence scope')
        for caption in (view.selection_heading, view.scope_label):
            self.assertTrue(caption.isVisible())
            self.assertTrue(caption.text())
            self.assertGreater(caption.width(), 0)
            self.assertGreaterEqual(caption.height(), caption.heightForWidth(caption.width()))
            parent = caption.parentWidget()
            self.assertTrue(parent.rect().contains(caption.rect().translated(caption.mapTo(parent, QPoint()))))

    def test_long_inspector_captions_wrap_inside_narrow_panes(self):
        from build_manager.review_ui import ReviewPlanView
        view = ReviewPlanView()
        self.addCleanup(view.close)
        view.reset(integrated(self.root), preview=False)
        view.inspect_phase('firebase')
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        view.selection_heading.setText('Selected task with a longer readable caption')
        view.scope_label.setText('Scope: task · Selected task with a longer readable caption')
        # Exercise the actual inspector pane, independently of the map toolbar's
        # larger native minimum width. No copied layout or relaxed control sizes.
        pane = view.sidebar_splitter.widget(1)
        pane.setParent(None)
        self.addCleanup(pane.close)
        pane.show()
        for _ in range(8): self.app.processEvents()
        for width in (360, 520):
            with self.subTest(width=width):
                pane.resize(width, 900)
                for _ in range(8): self.app.processEvents()
                self.assertEqual(pane.width(), width)
                for caption in (view.selection_heading, view.scope_label):
                    self.assertTrue(caption.isVisible())
                    self.assertGreater(caption.width(), 0)
                    self.assertGreaterEqual(caption.height(), caption.heightForWidth(caption.width()))
                    parent = caption.parentWidget()
                    self.assertTrue(parent.rect().contains(caption.rect().translated(caption.mapTo(parent, QPoint()))))
                    self.assertTrue(pane.rect().contains(caption.rect().translated(caption.mapTo(pane, QPoint()))))

    def test_active_repair_and_both_long_captions_fit_narrow_inspector(self):
        from build_manager.review_ui import ReviewPlanView
        view = ReviewPlanView()
        self.addCleanup(view.close)
        view.reset(integrated(self.root), preview=False)
        view.set_facts({'ios': dict(status='failed', error='Synthetic gate failure')})
        view.inspect_phase('firebase')
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        view.selection_heading.setText('Selected task with a longer readable caption')
        view.scope_label.setText('Scope: task · Selected task with a longer readable caption')
        pane = view.sidebar_splitter.widget(1)
        pane.setParent(None); self.addCleanup(pane.close)
        pane.show()
        for width in (360, 520):
            with self.subTest(width=width):
                pane.resize(width, 900)
                for _ in range(8): self.app.processEvents()
                self.assertEqual(pane.width(), width)
                self.assertTrue(view.blocker.isVisible())
                self.assertEqual(view.blocker.text(), 'View blocking step')
                self.assertGreaterEqual(view.blocker.width(), view.blocker.minimumSizeHint().width())
                self.assertGreaterEqual(view.blocker.height(), view.blocker.minimumSizeHint().height())
                for control in (view.selection_heading, view.scope_label, view.blocker):
                    self.assertTrue(control.isVisible())
                    if control is not view.blocker:
                        self.assertTrue(control.text())
                        self.assertGreaterEqual(control.height(), control.heightForWidth(control.width()))
                    parent = control.parentWidget()
                    self.assertTrue(parent.rect().contains(control.rect().translated(control.mapTo(parent, QPoint()))))
                    self.assertTrue(pane.rect().contains(control.rect().translated(control.mapTo(pane, QPoint()))))
        view.blocker.click()
        self.assertEqual(view.selected, 'ios')

    def test_task_font_refresh_preserves_manual_split_and_stops_on_close(self):
        view = self.panel.run_view.results_workspace
        self.panel.run_view.reset(integrated(self.root))
        view.inspect_phase('firebase')
        self.panel.stages.setCurrentIndex(2)
        self.window.resize(1280, 1100); self.window.show()
        for _ in range(8): self.app.processEvents()
        # Hold the available pane height constant; font-driven parent-window
        # changes are independent of preserving the user's splitter choice.
        view.sidebar_splitter.setParent(None)
        self.addCleanup(view.sidebar_splitter.close)
        view.sidebar_splitter.setFixedSize(900, 800)
        view.sidebar_splitter.show()
        for _ in range(8): self.app.processEvents()
        view.sidebar_splitter.setSizes([250, 400])
        view.manual_task_split = True
        sizes = view.sidebar_splitter.sizes()
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        for _ in range(8): self.app.processEvents()
        self.assertTrue(view.manual_task_split)
        self.assertEqual(view.sidebar_splitter.sizes(), sizes)
        current = view.tasks.currentItem()
        row = view.tasks.visualItemRect(current)
        self.assertGreater(row.height(), 0)
        self.assertGreaterEqual(view.tasks.minimumHeight(), view.tasks.header().height()
                                + row.height() + 2 * view.tasks.frameWidth())
        self.assertTrue(view._task_size_observer_active)
        view._task_size_timer.start(1000)
        view.close()
        self.assertFalse(view._task_size_timer.isActive())
        self.assertFalse(view._task_size_observer_active)
        view.show()
        for _ in range(8): self.app.processEvents()
        self.assertTrue(view._task_size_observer_active)

    def check_task_row_visible(self):
        tasks = self.panel.run_view.results_workspace.tasks
        tasks.scrollToItem(tasks.currentItem(), tasks.ScrollHint.PositionAtTop)
        self.app.processEvents()
        row = tasks.visualItemRect(tasks.currentItem())
        self.assertGreater(row.height(), 0)
        self.assertTrue(tasks.viewport().rect().contains(QRect(0, row.y(), tasks.viewport().width(), row.height())))
        header = tasks.header()
        self.assertTrue(tasks.rect().contains(header.rect().translated(header.mapTo(tasks, QPoint()))))

    def test_small_run_inspection_keeps_repair_action_inside_every_scroll_viewport(self):
        self.check_small_run_inspection()

    def check_small_run_inspection(self, *, extra_summary_height=0):
        panel = self.panel
        panel.run_view.reset(integrated(self.root))
        panel.run_view.update_phase(dict(id='ios', status='failed', error='Synthetic check failure'))
        panel.run_view.complete(dict(status='failed'))
        panel.stages.setCurrentIndex(2)
        grouped = panel.run_view.results_workspace.flow
        grouped.open_group('deliver.firebase')
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        self.window.resize(1024, 700); self.window.show()
        for _ in range(8): self.app.processEvents()
        if extra_summary_height:
            summary = panel.run_view.summary
            summary.setMinimumHeight(summary.height() + extra_summary_height)
            for _ in range(8): self.app.processEvents()
        button = panel.run_view.results_workspace.blocker
        panel.run_view.results_workspace.details_scroll.ensureWidgetVisible(button)
        self.app.processEvents()
        self.assertTrue(button.isVisible())
        ancestor = button.parentWidget()
        while ancestor:
            rect = button.rect().translated(button.mapTo(ancestor, QPoint()))
            self.assertTrue(ancestor.rect().contains(rect),
                f'{type(ancestor).__name__} name={ancestor.objectName()!r} '
                f'bounds={ancestor.rect().getRect()} button={rect.getRect()} '
                f'window={self.window.size().toTuple()} Qt={qVersion()} '
                f'style={self.app.style().objectName()} font={self.app.font().toString()} '
                f'DPI={self.app.primaryScreen().logicalDotsPerInch()}')
            ancestor = ancestor.parentWidget()
        button.click()
        self.assertEqual(panel.run_view.selected, 'ios')
        self.assertIn('Synthetic check failure', panel.run_view.detail.toPlainText())


if __name__ == '__main__':
    unittest.main()
