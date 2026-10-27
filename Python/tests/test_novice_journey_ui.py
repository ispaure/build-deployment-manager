"""Synthetic first-use walkthrough through real Qt/CLI retention and approvals."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from build_manager.approval_ui import EffectReviewDialog
from test_journeys import integrated
import test_toolbar_goals_ui as fixtures


class NoviceJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while self.panel.preparing or self.panel.reviewing or self.panel.history_loading or (
                self.panel.process.state() != QProcess.ProcessState.NotRunning):
            self.app.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline, self.panel.status.text())
        self.app.processEvents()

    def capture(self, name, widget=None):
        target = os.environ.get('BDM_WALKTHROUGH_CAPTURES')
        if target:
            root = Path(target)
            root.mkdir(parents=True, exist_ok=True)
            self.app.processEvents()
            (widget or self.window).grab().save(str(root / (name + '.png')))

    def review(self, select=None):
        def dialog(*args, **kwargs):
            result = EffectReviewDialog(*args, **kwargs)
            def decide():
                if select:
                    result.approvals[select].setChecked(True)
                self.capture('approval-' + (select or 'cancel'), result)
                if not select:
                    result.reject()
                else:
                    buttons = result.findChild(QDialogButtonBox)
                    next(button for button in buttons.buttons() if button.text().startswith('Approve')).click()
            QTimer.singleShot(0, decide)
            return result
        with patch('build_manager.ui.EffectReviewDialog', side_effect=dialog):
            self.panel.continue_run.click()
            self.wait_idle()

    def test_choose_review_start_delivers_and_return_from_history(self):
        fixture = fixtures.ToolbarGoalTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.window, self.panel = fixture.window, fixture.panel
        panel, view = self.panel, self.panel.configuration
        panel.project.make_journey = lambda *args, **kwargs: integrated(fixture.root)
        self.window.setFont(QFont(self.window.font().family(), 14))
        self.window.resize(1024, 700)
        self.window.show()
        self.app.processEvents()
        view.goal_buttons['deliver'].click()
        for control in panel.platform_checks.values():
            control.setChecked(False)
        view.blocker_actions['platforms'].click()
        self.assertIs(view.config_tabs.currentWidget(), view.config_pages['platforms'])
        self.capture('01-choose-platforms')
        for control in (*panel.platform_checks.values(), *panel.destination_checks.values()):
            control.setChecked(True)
        panel.prepare.click()
        self.wait_idle()
        self.assertTrue(panel.start.isEnabled())
        self.capture('02-review')
        panel.start.click()
        self.wait_idle()
        original = panel.result
        first = json.loads(original.read_text())
        self.assertEqual(first['status'], 'passed')
        self.capture('03-delivered')
        self.assertEqual(panel.stages.currentIndex(), 2)
        self.assertEqual(panel.run_view.outcome, 'passed')
        self.assertFalse(panel.continue_run.isEnabled())
        self.assertTrue((fixture.root / 'firebase.json').exists())
        self.assertTrue((fixture.root / 'testflight.json').exists())
        panel.run_view.inspect_summary_phase('firebase')
        panel.run_view.tabs.setCurrentWidget(panel.run_view.delivery_page)
        self.capture('04-delivery-evidence')
        report = json.loads(original.read_text())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(panel.run_view.workflow_action.text(), '2 of 2 destinations delivered · 1 retained file')
        self.assertEqual(panel.result, original)
        self.assertEqual(first['phases'][2]['started_at'], report['phases'][2]['started_at'])
        self.capture('05-completed')
        panel.past_runs.click()
        self.wait_idle()
        panel.history_view.filter.setCurrentIndex(2)
        self.capture('06-history')
        panel.history.setCurrentItem(panel.history.topLevelItem(0))
        panel.view_history_button.click()
        self.assertEqual(panel.run_view.outcome, 'passed')
        self.assertEqual(panel.run_view.run_choices.flow.pages.currentIndex(), 0)
        self.assertFalse(panel.continue_run.isEnabled())
        self.capture('07-reopened')

    def test_failed_gate_leads_to_its_evidence_without_running_deliveries(self):
        fixture = fixtures.ToolbarGoalTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.window, self.panel = fixture.window, fixture.panel
        panel = self.panel
        panel.project.make_journey = lambda *args, **kwargs: integrated(fixture.root, fail_gate=True)
        self.window.resize(1024, 700)
        self.window.show()
        panel.configuration.goal_buttons['deliver'].click()
        for control in (*panel.platform_checks.values(), *panel.destination_checks.values()):
            control.setChecked(True)
        panel.prepare.click()
        self.wait_idle()
        panel.start.click()
        self.wait_idle()
        self.assertEqual(panel.run_view.outcome, 'failed')
        self.capture('08-failed-gate')
        panel.run_problems.click()
        self.assertEqual(panel.run_view.selected, 'ios')
        self.assertIn('State: Failed', panel.run_view.detail.toPlainText())
        self.assertFalse((fixture.root / 'firebase.json').exists())
        self.assertFalse((fixture.root / 'testflight.json').exists())
        self.capture('09-failure-evidence')
