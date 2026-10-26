"""Direct repairs and readable, navigable maps without changing executable work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
import sys
import unittest
from unittest.mock import Mock

from PySide6.QtCore import QPoint, Qt, QRectF
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from build_manager import Phase, Plan
from build_manager.ui import ManagerPanel
from build_manager.run_ui import RunView
from build_manager.workflow_ui import WorkflowFlow
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
        self.assertIs(view.delivery_tabs.currentWidget(), view.delivery_categories['Mobile dev devices'][0])
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

    def test_map_has_readable_floor_and_keyboard_reveals_offscreen_cards(self):
        plan = self.long_plan(); before = plan.data()
        flow = WorkflowFlow(); self.addCleanup(flow.close)
        flow.resize(600, 500); flow.reset(plan, preview=True); flow.map_button.click(); flow.show()
        for _ in range(5): self.app.processEvents()
        self.assertGreater(flow.scroll.horizontalScrollBar().maximum(), 0)
        for _ in range(8): flow.scroll.zoom(.5)
        self.assertEqual(flow.scroll.transform().m11(), flow.scroll.minimum_scale)
        card = flow.canvas.cards['step-11'][0]
        card.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        rect = flow.scroll.mapFromScene(flow.scroll.proxy.mapRectToScene(QRectF(card.geometry()))).boundingRect()
        self.assertTrue(flow.scroll.viewport().rect().contains(rect))
        QTest.keyClick(card, Qt.Key.Key_Space)
        self.assertEqual(flow.selected, 'step-11')
        self.assertEqual(plan.data(), before)
        self.assertTrue(card.findChild(QLabel, 'approvalBadge').isVisible())
        flow.set_facts({'step-11': dict(status='passed')})
        self.assertTrue(card.findChild(QLabel, 'approvalBadge').isHidden())

    def test_status_updates_preserve_map_pan_and_manual_zoom(self):
        flow = WorkflowFlow(); self.addCleanup(flow.close)
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
        grouped = view.run_choices.flow
        grouped.open_group('deliver.firebase')
        self.assertEqual(view.blocking_key, 'ios')
        view.blocking_step.click()
        self.assertEqual(view.pages.currentIndex(), 0)
        self.assertEqual(view.selected, 'ios')
        self.assertIs(view.tabs.currentWidget(), view.steps.parentWidget())
        self.assertEqual(plan.data(), before)

    def test_small_run_inspection_keeps_repair_action_inside_every_scroll_viewport(self):
        panel = self.panel
        panel.run_view.reset(integrated(self.root))
        panel.run_view.update_phase(dict(id='ios', status='failed', error='Synthetic check failure'))
        panel.run_view.complete(dict(status='failed'))
        panel.stages.setCurrentIndex(2)
        grouped = panel.run_view.run_choices.flow
        grouped.open_group('deliver.firebase')
        original = QFont(self.app.font()); self.addCleanup(self.app.setFont, original)
        font = QFont(original); font.setPointSize(14); self.app.setFont(font)
        self.window.resize(1024, 700); self.window.show()
        for _ in range(8): self.app.processEvents()
        button = panel.run_view.blocking_step
        self.assertTrue(button.isVisible())
        ancestor = button.parentWidget()
        while ancestor:
            rect = button.rect().translated(button.mapTo(ancestor, QPoint()))
            self.assertTrue(ancestor.rect().contains(rect), type(ancestor).__name__)
            ancestor = ancestor.parentWidget()
        button.click()
        self.assertEqual(panel.run_view.selected, 'ios')
        self.assertIn('Synthetic check failure', panel.run_view.detail.toPlainText())


if __name__ == '__main__':
    unittest.main()
