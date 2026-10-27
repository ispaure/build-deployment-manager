"""Live summary updates keep evidence readable and problems directly accessible."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from tempfile import TemporaryDirectory
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.run_ui import RunView


class SummaryReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.view = RunView()
        self.addCleanup(self.view.close)
        plan = Plan('Fixture', 'Test', {}, tuple(
            Phase(key, (sys.executable, '-V'), directory.name) for key in ('check', 'other')), directory.name)
        self.view.reset(plan)
        self.view.resize(1000, 700)
        self.view.show()
        self.summary = self.view.run_choices.flow
        self.summary.open_group('operation')
        self.view.flow.canvas.cards['check'][0].click()
        self.view.update_phase(dict(id='check', status='failed', error='Failure headline\n' + '\n'.join(
            f'Evidence line {i}' for i in range(150))))
        self.app.processEvents()

    def test_ticks_and_changed_evidence_preserve_scroll_and_selection(self):
        details = self.view.detail
        cursor = details.textCursor()
        cursor.setPosition(20)
        cursor.setPosition(30, cursor.MoveMode.KeepAnchor)
        details.setTextCursor(cursor)
        bar = details.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        value = bar.value()
        self.assertGreater(value, 0)
        selected = details.textCursor().selectedText()
        self.view.tick()
        self.view.update_phase(dict(id='other', status='running'))
        self.assertEqual(bar.value(), value)
        self.assertEqual(details.textCursor().selectedText(), selected)
        self.view.update_phase(dict(id='check', status='failed', summary='Additional evidence'))
        self.assertEqual(bar.value(), value)
        self.assertEqual(details.textCursor().selectedText(), selected)
        self.view.flow.canvas.cards['other'][0].click()
        self.assertEqual(bar.value(), 0)

    def test_failure_precedes_context_and_button_opens_step_evidence(self):
        text = self.view.detail.toPlainText()
        self.assertLess(text.index('Failure headline'), text.index('Dependencies:'))
        self.view.attention_problems.click()
        self.assertEqual(self.view.selected, 'check')
        self.assertIs(self.view.run_choices.inspector_tabs.currentWidget(), self.view.run_choices.details_scroll)
        self.assertIn('Failure headline', self.view.detail.toPlainText())

    def test_problem_action_scopes_tests_and_selects_failure_message(self):
        case = dict(name='broken check', classname='Fixture', suite='Checks', status='failed', seconds=.1,
                    message='Expected a valid result')
        self.view.update_phase(dict(id='check', status='failed', tests=[case]))
        self.assertIn(case['message'], self.view.detail.toPlainText())
        self.view.attention_problems.click()
        self.assertEqual(self.view.selected, 'check')
        self.assertEqual(self.view.tabs.currentWidget(), self.view.tests.parentWidget())
        self.assertEqual(self.view.filter.currentText(), 'Problems')
        self.assertIsNotNone(self.view.tests.currentItem())
        self.assertIn(case['message'], self.view.test_detail.toPlainText())
