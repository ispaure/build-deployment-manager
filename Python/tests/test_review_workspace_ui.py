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
from PySide6.QtCore import QPoint, QProcess, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
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

    def test_sidebar_uses_independent_tree_and_details_panes_without_outer_scroll(self):
        view = self.view
        self.assertNotIsInstance(view.inspector, QScrollArea)
        self.assertIs(view.inspector_scroll, view.inspector)
        self.assertEqual(view.sidebar_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(view.sidebar_splitter.count(), 2)
        self.assertTrue(view.sidebar_splitter.widget(0).isAncestorOf(view.tasks))
        self.assertTrue(view.sidebar_splitter.widget(1).isAncestorOf(view.inspector_tabs))
        view.sidebar_splitter.setSizes([250, 300])
        self.app.processEvents()
        sizes = view.sidebar_splitter.sizes()
        view.set_facts({'android': dict(status='running')})
        self.app.processEvents()
        self.assertEqual(view.sidebar_splitter.sizes(), sizes)

    def test_single_task_card_stays_on_overview_with_its_own_card_and_task_details(self):
        view = self.view
        view.flow.canvas.cards['deliver.firebase'][0].click()
        self.assertEqual(view.flow.pages.currentIndex(), 0)
        self.assertTrue(view.graph.isHidden())
        self.assertEqual(view.selected, 'firebase')
        self.assertEqual(set(view.rows), {'firebase'})
        self.assertEqual(view.tasks.topLevelItemCount(), 1)
        self.assertIs(view.rows['firebase'].parent(), view.card_rows['deliver.firebase'])
        self.assertIn('firebase:fixture', view.fact_values['Delivery'].text())
        view.flow.canvas.cards['platform.android'][0].click()
        self.assertEqual(view.flow.pages.currentIndex(), 0)
        self.assertEqual(set(view.rows), {'environment', 'android'})
        self.assertTrue(view.graph.isHidden())

    def test_task_expands_reported_cases_and_keeps_selection_during_live_updates(self):
        view = self.view
        view.flow.open_group('platform.android')
        case = dict(name='test_one', classname='Shared.Contracts', suite='shared',
                    status='passed', seconds=.2, message='Measured case details')
        fact = dict(status='running', tests_provisional=True, live_tests=[case])
        view.set_facts({'android': fact})
        row = view.rows['android']
        self.assertEqual(row.childCount(), 1)
        row.setExpanded(True)
        child = row.child(0)
        view.tasks.setCurrentItem(child)
        self.assertEqual(view.selected, 'android')
        self.assertIn('Measured case details', view.case_detail.text())
        view.set_facts({'android': dict(fact, live_tests=[case, dict(case, name='test_two')])})
        self.assertTrue(row.isExpanded())
        self.assertIs(row.child(0), child)
        self.assertIs(view.tasks.currentItem(), child)
        self.assertEqual(row.childCount(), 2)
        view.set_facts({'android': dict(status='passed', tests=[case], live_tests=[], tests_provisional=False)})
        self.assertEqual(row.childCount(), 1)
        self.assertEqual(child.text(1), 'Passed')

    def test_files_group_into_folders_before_run_then_show_current_test_and_time_shares(self):
        from datetime import datetime, timezone
        phase = Phase('commonutils', (sys.executable, '-V'), str(self.root),
            test_files=('appearance/test_theme.py', 'appearance/test_fonts.py', 'storage/test_cache.py'))
        other = Phase('other', (sys.executable, '-V'), str(self.root))
        plan = replace(self.plan, phases=(phase, other), journey={})
        self.panel.present_plan(plan)
        view = self.view
        row = view.rows['commonutils']
        self.assertEqual(row.childCount(), 2)
        appearance = row.child(0)
        self.assertEqual(appearance.text(0), 'appearance')
        self.assertEqual(appearance.childCount(), 2)
        self.assertEqual(appearance.child(0).text(0), 'test_theme.py')
        self.assertEqual(appearance.child(0).childCount(), 0)
        current = dict(name='test_current', classname='Shared.Theme', file='appearance/test_theme.py',
                       status='running', started_at=datetime.now(timezone.utc).isoformat())
        facts = {'commonutils': dict(status='running', seconds=20, current_test=current,
                 test_files=[dict(name='appearance/test_theme.py', status='running', seconds=10)],
                 live_tests=[dict(name='test_done', classname='Shared.Theme', file='appearance/test_theme.py',
                                  status='passed', seconds=2, message='')], tests_provisional=True),
                 'other': dict(status='passed', seconds=80)}
        view.set_facts(facts)
        self.assertIs(view.rows['commonutils'], row)
        self.assertIs(row.child(0), appearance)
        file = appearance.child(0)
        self.assertEqual([file.child(i).text(0) for i in range(file.childCount())], ['test_done', 'test_current'])
        self.assertEqual(file.child(1).text(1), 'Running')
        self.assertEqual(row.data(2, Qt.ItemDataRole.UserRole), .2)
        # Each level divides its measured siblings, independent of wall time.
        row.setExpanded(True)
        appearance.setExpanded(True)
        file.setExpanded(True)
        self.assertEqual(appearance.data(2, Qt.ItemDataRole.UserRole), 1)
        self.assertEqual(file.data(2, Qt.ItemDataRole.UserRole), 1)
        shares = [file.child(i).data(2, Qt.ItemDataRole.UserRole) for i in range(file.childCount())]
        self.assertAlmostEqual(sum(shares), 1)
        self.assertEqual(file.text(0), 'test_theme.py')

    def test_time_shares_renormalize_each_level_as_sibling_results_arrive(self):
        phases = tuple(Phase(key, (sys.executable, '-V'), str(self.root)) for key in ('commonutils', 'other'))
        self.panel.present_plan(replace(self.plan, phases=phases, journey={}))
        view = self.view
        facts = {'commonutils': dict(status='passed', seconds=10, tests=[
            dict(name='small', file='shared/test_api.py', status='passed', seconds=.025),
            dict(name='large', file='shared/test_api.py', status='passed', seconds=.075)]),
            'other': dict(status='running', seconds=90)}
        view.set_facts(facts)
        row = view.rows['commonutils']
        folder = row.child(0)
        file = folder.child(0)
        for item in (row, folder, file):
            item.setExpanded(True)
        self.assertEqual(row.data(2, Qt.ItemDataRole.UserRole), .1)
        self.assertEqual(folder.data(2, Qt.ItemDataRole.UserRole), 1)
        self.assertEqual(file.data(2, Qt.ItemDataRole.UserRole), 1)
        self.assertAlmostEqual(file.child(0).data(2, Qt.ItemDataRole.UserRole), .25)
        self.assertAlmostEqual(file.child(1).data(2, Qt.ItemDataRole.UserRole), .75)
        self.assertEqual(file.child(0).text(2), '25ms')
        facts['other']['seconds'] = 190
        facts['commonutils']['tests'].append(dict(name='new', file='shared/test_api.py', status='passed', seconds=.1))
        view.set_facts(facts)
        self.assertEqual(row.data(2, Qt.ItemDataRole.UserRole), .05)
        self.assertIs(row.child(0).child(0), file)
        self.assertEqual(row.text(2), '10s')
        self.assertAlmostEqual(file.child(0).data(2, Qt.ItemDataRole.UserRole), .125)
        self.assertAlmostEqual(sum(file.child(i).data(2, Qt.ItemDataRole.UserRole) for i in range(3)), 1)
        self.assertIsNone(view.tasks.itemWidget(file.child(0), 2))
        row.setExpanded(False)
        row.setExpanded(True)
        self.assertAlmostEqual(file.child(0).data(2, Qt.ItemDataRole.UserRole), .125)

    def test_reused_subtree_has_no_current_timing_and_keeps_historical_tooltips(self):
        phases = tuple(Phase(key, (sys.executable, '-V'), str(self.root)) for key in ('commonutils', 'other'))
        self.panel.present_plan(replace(self.plan, phases=phases, journey={}))
        view = self.view
        tests = [dict(name='test_cached', file='shared/test_api.py', status='passed', seconds=.025)]
        fact = dict(status='passed', seconds=10, tests=tests)
        view.set_facts({'commonutils': fact, 'other': dict(status='passed', seconds=90)})
        row = view.rows['commonutils']
        folder = row.child(0)
        file = folder.child(0)
        case = file.child(0)
        for item in (row, folder, file):
            item.setExpanded(True)
        # Even identical descendants must refresh when reuse status changes.
        cached = dict(fact, reused=True, reuse=dict(original_seconds=10))
        view.set_facts({'commonutils': cached, 'other': dict(status='passed', seconds=90)})
        self.assertEqual(row.text(1), 'Reused')
        for item in (row, folder, file, case):
            self.assertEqual(item.text(2), '—')
            self.assertIsNone(item.data(2, Qt.ItemDataRole.UserRole))
            self.assertIn('Previous run:', item.toolTip(2))
            self.assertIn('Reused result', item.data(2, Qt.ItemDataRole.AccessibleTextRole))
        self.assertIn('10s', row.toolTip(2))
        self.assertIn('25ms', case.toolTip(2))
        self.assertEqual(view.rows['other'].data(2, Qt.ItemDataRole.UserRole), 1)
        self.assertEqual(row.parent().text(2), '90s')
        cached['seconds'] = 0  # Actual retained evidence uses zero for this run.
        view.set_facts({'commonutils': cached})
        self.assertEqual(row.parent().text(2), '—')
        self.assertIsNone(row.parent().data(2, Qt.ItemDataRole.UserRole))
        row.setExpanded(False)
        row.setExpanded(True)
        self.assertEqual(case.text(2), '—')
        self.assertEqual(case.data(0, Qt.ItemDataRole.UserRole + 1)['seconds'], .025)
        # A fresh execution restores normal timing without rebuilding the tree.
        view.set_facts({'commonutils': fact})
        self.assertIs(row.child(0).child(0).child(0), case)
        self.assertEqual(row.text(2), '10s')
        self.assertEqual(case.text(2), '25ms')
        self.assertEqual(case.data(2, Qt.ItemDataRole.UserRole), 1)

    def test_one_persistent_inspector_syncs_keyboard_card_task_and_dependency_selection(self):
        view = self.view
        self.assertEqual([view.inspector_tabs.tabText(i) for i in range(view.inspector_tabs.count())],
                         ['Details', 'Command', 'Plan'])
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
        self.assertEqual(view.selected, 'android')
        self.assertTrue(view.flow.canvas.cards['platform.android'][0].isChecked())
        self.assertEqual(view.prerequisite_layout.itemAt(1).widget().full_text, 'Check environment')
        self.assertTrue(view.error_panel.isHidden())
        self.assertTrue(view.fact_values['Elapsed'].isHidden())
        self.assertTrue(view.fact_values['Runs on'].text())
        view.tasks.setCurrentItem(view.rows['environment'])
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
        self.assertEqual(view.selected, 'prepare')
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
        self.assertIs(self.view.inspector_tabs.currentWidget(), self.view.details_scroll)
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
        view.inspect_phase('testflight')
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
        view.inspector_tabs.setCurrentWidget(view.command)
        self.assertIn(sys.executable, view.command.toPlainText())
        self.assertIn(str(self.root), view.command.toPlainText())
        view.inspector_tabs.setCurrentWidget(view.plan_tabs)
        view.plan_tabs.setCurrentWidget(view.plan_data)
        self.assertEqual(json.loads(view.plan_data.toPlainText())['project'], self.plan.project)
        view.inspector_tabs.setCurrentWidget(view.details_scroll)
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
        self.assertEqual(view.selected, 'environment')
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
        minima = [(type(widget).__name__, widget.objectName(), widget.minimumSizeHint().toTuple())
                  for widget in (self.panel, *self.panel.findChildren(QWidget))
                  if widget.isVisible() and widget.minimumSizeHint().width() > 300]
        self.assertEqual((self.panel.width(), self.panel.height()), (1024, 700), minima)
        for button in (self.panel.start, self.panel.back):
            self.assertTrue(self.panel.rect().contains(button.rect().translated(button.mapTo(self.panel, QPoint()))))
        self.assertTrue(self.view.tasks.isVisible())
        self.assertTrue(self.view.fact_panel.isVisible())
        self.assertTrue(self.view.error_panel.isHidden())
        self.assertTrue(self.view.graph.guidance.isHidden())
        self.assertTrue(self.view.graph.legend.isHidden())
        self.assertTrue(self.panel.stage_heading.isHidden())
        self.assertTrue(self.panel.action_footer.isAncestorOf(self.panel.review_help))

    def test_long_source_caption_fits_and_retains_accessible_full_text(self):
        caption = 'Captured source: ' + 'source-and-run-choices ' * 40
        button = self.view.source_details.toggle
        button.setText(caption)
        self.panel.resize(1024, 700)
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual(self.panel.width(), 1024)
        self.assertNotEqual(button.text(), caption)
        self.assertEqual(button.accessibleName(), caption)
        self.assertEqual(button.toolTip(), caption)
        button.click()
        self.assertTrue(self.view.source_details.content.isVisible())

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
