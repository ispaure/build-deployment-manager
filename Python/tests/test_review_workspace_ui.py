"""A single review workspace synchronizes map, task list and crash evidence."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QProcess, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget
from build_manager import Phase
from build_manager.ui import ManagerPanel
from test_journeys import integrated
from test_ui import OtherProject


class ReviewWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(self.panel.close)
        base = integrated(self.root)
        env = Phase('environment', (sys.executable, '-V'), str(self.root), label='Check environment')
        self.plan = replace(base, phases=(env, replace(base.phases[0], dependencies=('environment',)), *base.phases[1:]))
        self.before = self.plan.data()
        self.panel.present_plan(self.plan)
        self.panel.stages.setCurrentIndex(1)
        self.view = self.panel.review_workspace
        self.panel.resize(1100, 800)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.assertEqual(self.plan.data(), self.before)
        self.assertEqual(self.panel.process.state(), QProcess.ProcessState.NotRunning)

    def test_unprepared_review_map_can_be_painted_before_a_plan_exists(self):
        panel = ManagerPanel(OtherProject(self.root))
        self.addCleanup(panel.close)
        panel.resize(1024, 700)
        panel.show()
        panel.stages.setCurrentIndex(1)
        self.app.processEvents()
        self.assertFalse(panel.review_workspace.flow.canvas.cards)
        self.assertFalse(panel.grab().isNull())
        panel.stages.setCurrentIndex(0)
        self.app.processEvents()

    def test_one_persistent_inspector_syncs_keyboard_card_task_and_dependency_selection(self):
        view = self.view
        self.assertFalse(view.findChildren(QTabWidget))
        inspector = view.inspector_scroll
        self.assertTrue(inspector.isVisible())
        self.assertEqual(set(view.rows), {phase.id for phase in self.plan.phases})
        card = view.flow.canvas.cards['platform.android'][0]
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Space)
        self.assertEqual(set(view.rows), {'environment', 'android'})
        self.assertTrue(view.graph.whole.isHidden())
        self.assertEqual(view.selected, 'environment')
        view.tasks.setCurrentItem(view.rows['android'])
        self.assertEqual(view.graph.selected, 'android')
        self.assertTrue(view.graph.canvas.cards['android'][0].isChecked())
        self.assertEqual(view.prerequisite_layout.itemAt(1).widget().full_text, 'Check environment')
        self.assertTrue(view.error_panel.isHidden())
        self.assertTrue(view.fact_values['Elapsed'].isHidden())
        self.assertTrue(view.fact_values['Runs on'].text())
        view.graph.canvas.cards['environment'][0].click()
        self.assertIs(view.tasks.currentItem(), view.rows['environment'])
        view.flow.back.click()
        self.assertIs(view.inspector_scroll, inspector)
        self.assertTrue(inspector.isVisible())
        self.assertEqual(view.tasks.currentItem(), None)
        view.tasks.setCurrentItem(view.rows['firebase'])
        self.assertEqual(view.flow.selected, 'deliver.firebase')
        self.assertEqual(view.selected, 'firebase')
        self.assertIn('firebase:fixture', view.fact_values['Delivery'].text())
        self.assertIn('separate approval', view.fact_values['Delivery'].text().lower())
        button = view.prerequisite_layout.itemAt(1).widget()
        button.click()
        self.assertEqual(view.graph.selected, 'prepare')
        self.assertIs(view.tasks.currentItem(), view.rows['prepare'])
        view.flow.back.click()
        view.flow.open_group('source')
        self.assertFalse(view.rows)
        self.assertTrue(view.graph.isHidden())
        self.assertIn('No executable source subtasks', view.context_info.text())
        self.assertTrue(inspector.isVisible())

    def test_repeated_task_prefixes_are_shortened_and_normal_steps_have_no_text_dump(self):
        keys = ('commonutils', 'portable-contracts', 'desktop-ui', 'mobile-host')
        phases = tuple(Phase('android.validation.' + key, (sys.executable, '-V'), str(self.root)) for key in keys)
        plan = replace(self.plan, phases=phases, journey={})
        self.panel.present_plan(plan)
        self.view.flow.open_group('operation')
        self.assertEqual([row.text(0) for row in self.view.rows.values()],
                         ['Commonutils', 'Portable contracts', 'Desktop ui', 'Mobile host'])
        for key, row in self.view.rows.items():
            self.assertIn(key, row.toolTip(0))
        self.assertFalse(self.view.details.isVisible())
        self.assertTrue(self.view.error_panel.isHidden())
        self.assertFalse(self.view.command_section.toggle.isChecked())
        self.assertIn('Timeout:', self.view.command.toPlainText())
        self.assertTrue(self.view.graph.guidance.isHidden())
        self.assertTrue(self.view.graph.legend.isHidden())
        self.assertIn('Drag to pan', self.view.graph.scroll.toolTip())

    def test_step_execution_location_comes_from_its_own_platform(self):
        plan = replace(self.plan, backend='Per-platform execution choices', journey=dict(self.plan.journey,
            executions={'android': dict(backend='This Mac · Android Emulator'),
                        'ios': dict(backend='This Mac · iOS Simulators')}))
        self.panel.present_plan(plan)
        self.view.flow.open_group('platform.android')
        self.view.inspect_phase('environment')
        self.assertEqual(self.view.fact_values['Runs on'].text(), 'This Mac · Android Emulator')

    def test_failure_action_finds_crash_outside_current_card_and_blocker_is_direct(self):
        view = self.view
        view.set_facts({'environment': dict(status='error', error='RuntimeError: tool crashed\nTraceback detail',
            exit_code=7, seconds=2.5, log='environment.log', tests=[dict(name='broken case', status='error', message='Expected tool output')])})
        view.log_reader = lambda key: 'Captured stderr: missing plugin\nlast diagnostic line'
        view.flow.open_group('deliver.testflight')
        view.graph.select('testflight')
        self.assertTrue(view.problems.isVisible())
        view.problems.click()
        self.assertEqual(view.selected, 'environment')
        self.assertIs(view.tasks.currentItem(), view.rows['environment'])
        text = view.details.toPlainText()
        for value in ('RuntimeError: tool crashed', 'Traceback detail', 'Exit code: 7', 'Expected tool output', 'last diagnostic line'):
            self.assertIn(value, text)
        self.assertTrue(view.error_panel.isVisible())
        self.assertIn('tool crashed', view.error_summary.text())
        self.assertEqual(view.fact_values['Elapsed'].text(), '2.50s')
        self.assertNotIn('Starts after:', text)
        view.inspect_phase('android')
        self.assertTrue(view.blocker.isVisible())
        view.blocker.click()
        self.assertEqual(view.selected, 'environment')
        view.command_section.toggle.click()
        self.assertIn(sys.executable, view.command.toPlainText())
        self.assertIn(str(self.root), view.command.toPlainText())
        view.technical_section.toggle.click()
        self.assertEqual(json.loads(view.plan_data.toPlainText())['project'], self.plan.project)
        self.assertTrue(view.details.isVisible())

    def test_updates_keep_selected_evidence_and_scroll_and_reset_clears_old_failure(self):
        view = self.view
        facts = {'environment': dict(status='failed', error='\n'.join(f'Crash line {i}' for i in range(150)))}
        view.set_facts(facts)
        view.problems.click()
        cursor = view.details.textCursor()
        cursor.setPosition(20)
        cursor.setPosition(30, cursor.MoveMode.KeepAnchor)
        view.details.setTextCursor(cursor)
        bar = view.details.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        value, selected = bar.value(), cursor.selectedText()
        view.set_facts(dict(facts, ios=dict(status='running')))
        self.assertEqual(bar.value(), value)
        self.assertEqual(view.details.textCursor().selectedText(), selected)
        self.assertEqual(view.graph.selected, 'environment')
        view.set_facts(dict(facts, environment=dict(facts['environment'], summary='More evidence')))
        self.assertEqual(bar.value(), value)
        self.panel.present_plan(self.plan)
        self.assertFalse(view.problems.isVisible())
        self.assertNotIn('Crash line', view.details.toPlainText())
        self.assertTrue(all(view.rows[key].text(2) == '—' and view.rows[key].toolTip(2) == 'Not started' for key in view.rows))

    def test_laptop_footer_and_inspector_remain_reachable_with_large_font(self):
        original = QFont(self.app.font())
        self.addCleanup(self.app.setFont, original)
        font = QFont(original)
        font.setPointSize(14)
        self.app.setFont(font)
        self.panel.resize(1024, 700)
        self.view.flow.open_group('deliver.firebase')
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual((self.panel.width(), self.panel.height()), (1024, 700))
        for button in (self.panel.start, self.panel.back):
            self.assertTrue(self.panel.rect().contains(button.rect().translated(button.mapTo(self.panel, QPoint()))))
        self.assertTrue(self.view.tasks.isVisible())
        self.assertTrue(self.view.fact_panel.isVisible())
        self.assertTrue(self.view.error_panel.isHidden())
        self.assertTrue(self.view.graph.guidance.isHidden())
        self.assertTrue(self.view.graph.legend.isHidden())
        self.assertTrue(self.panel.stage_heading.isHidden())
        self.assertTrue(self.panel.action_footer.isAncestorOf(self.panel.review_help))

    def test_preparation_failure_exposes_full_redacted_traceback_without_starting_work(self):
        self.panel.stages.setCurrentIndex(0)
        def crash(*args, **kwargs):
            raise RuntimeError('Adapter exploded: secret-fixture-value')
        self.panel.project.make_plan = crash
        from build_manager.redaction import Redactor
        self.panel.redact = Redactor(['secret-fixture-value'])
        self.panel.inspect_plan()
        deadline = time.monotonic() + 5
        while self.panel.preparing:
            self.app.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline)
        self.assertTrue(self.panel.preparation_error_section.isVisible())
        text = self.panel.preparation_error.toPlainText()
        self.assertIn('Traceback', text)
        self.assertIn('RuntimeError', text)
        self.assertIn('Adapter exploded', text)
        self.assertNotIn('secret-fixture-value', text)
        self.assertFalse(self.panel.start.isEnabled())
