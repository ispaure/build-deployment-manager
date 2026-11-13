"""Balanced presentation keeps scope, editability and explicit action contracts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PySide6.QtCore import Qt, QCoreApplication, QEvent, QThreadPool
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication, QTabBar, QTabWidget, QWidget, QFormLayout, QLineEdit, QComboBox, QSpinBox

from build_manager.accounts_ui import AccountsDialog
from build_manager.configuration_ui import ConfigurationView
from build_manager.run_ui import RunView
from build_manager.run_output_ui import RunOutputView
from build_manager.run_fields_ui import RunFieldsView
from build_manager.recipient_ui import RecipientPicker
from build_manager.settings import SettingsStore
from build_manager.ui import ManagerPanel
from build_manager.ui_components import EvidenceNavigator, HeadingLabel, install_font_refresh
from build_manager.vm_ui import VMDialog
from test_journeys import CAPABILITY, integrated
from test_ui import OtherProject


class BalancedWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.font = QFont(self.app.font())

    def tearDown(self):
        self.app.setFont(self.font)
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QThreadPool.globalInstance().waitForDone(5000)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def pump(self):
        for _ in range(4): self.app.processEvents()

    def project(self):
        project = OtherProject(self.root)
        project.journey_capability = deepcopy(CAPABILITY)
        for row in project.journey_capability['destinations'].values():
            row['category'] = 'Mobile tester platforms'
        return project

    def test_destination_groups_are_simultaneously_reachable_without_changing_choices(self):
        view = ConfigurationView(self.project())
        view.goal_buttons['deliver'].click()
        view.destination_checks['firebase'].setChecked(True)
        view.destination_checks['testflight'].setChecked(True)
        before = view.choices()
        view.open_section('delivery', 'testflight')
        view.resize(1100, 700); view.show(); self.pump()
        self.assertFalse(view.delivery_options.findChildren(QTabWidget))
        for target in ('firebase', 'testflight'):
            self.assertFalse(view.destination_groups[target].isHidden())
            self.assertFalse(view.destination_options[target].isHidden())
        self.assertEqual(view.choices(), before)

    def test_run_evidence_selector_keeps_source_records_in_a_disclosure(self):
        view = RunView(); view.reset(integrated(self.root))
        nav = view.results_workspace.inspector_tabs
        self.assertIsInstance(nav, EvidenceNavigator)
        self.assertFalse(nav.findChildren(QTabBar))
        labels = lambda selector: [selector.itemText(index) for index in range(selector.count())]
        self.assertEqual(labels(nav.selector), ['Summary', 'Logs', 'Deliveries'])
        disclosure = view.results_workspace.technical_section
        self.assertTrue(disclosure.content.isHidden())
        view.set_report(dict(status='passed', marker='Only in the run report'))
        disclosure.toggle.click()
        self.assertFalse(disclosure.content.isHidden())
        technical = view.technical.navigator
        self.assertEqual(labels(technical.selector), [
            'Step command', 'Plan overview', 'Dependencies', 'Plan data', 'Step record', 'Run report'])
        for page in (view.results_workspace.plan_data, view.report_view):
            technical.selector.setCurrentIndex(technical.selector.findData(page))
            self.assertIs(technical.currentWidget(), page)
            self.assertIs(nav.currentWidget(), view.summary_page)
        self.assertIn('Only in the run report', view.report_view.toPlainText())
        self.assertNotIn('Only in the run report', view.log.toPlainText())
        view.set_storage_maintenance(dict(status='incomplete'))
        self.assertEqual(labels(technical.selector)[-1], 'Storage maintenance')
        technical.setCurrentWidget(view.storage_view)
        self.assertIn('incomplete', view.storage_view.toPlainText())
        self.assertNotIn('incomplete', view.log.toPlainText())
        view.results_workspace.inspect_phase('android')
        nav.setCurrentWidget(view.output)
        view.results_workspace.flow.open_group('deliver.firebase')
        self.assertIs(nav.currentWidget(), view.output)
        self.assertIn('Firebase', view.results_workspace.scope_label.text())
        self.assertEqual(set(view.scoped_facts()), {'firebase'})
        self.assertEqual(labels(nav.selector), ['Summary', 'Logs', 'Deliveries'])

    def test_captured_summary_visible_and_live_refresh_preserves_manual_panes(self):
        panel = ManagerPanel(self.project()); plan = integrated(self.root)
        before = plan.data()
        panel.present_plan(plan); panel.stages.setCurrentIndex(1)
        panel.resize(1280, 800); panel.show(); self.pump()
        view = panel.review_workspace
        self.assertTrue(view.captured_summary.isVisible())
        for value in ('fixed', 'android', 'ios', 'firebase:fixture/app/testers'):
            self.assertIn(value, view.captured_summary.text())
        self.assertTrue(view.source_details.content.isHidden())
        view.sidebar_splitter.setSizes([210, 260]); sizes = view.sidebar_splitter.sizes()
        view.set_facts({'android': dict(status='running')}); self.pump()
        self.assertEqual(view.sidebar_splitter.sizes(), sizes)
        self.assertEqual(plan.data(), before)

    def test_font_scaling_reflows_controls_and_keeps_primary_action_reachable(self):
        panel = ManagerPanel(self.project())
        panel.resize(1024, 700); panel.show(); self.pump()
        for size in (18, 28):
            font = QFont(self.font); font.setPointSize(size); self.app.setFont(font)
            self.pump()
            config = panel.configuration
            if size == 28:
                self.assertEqual(config.splitter.orientation(), Qt.Orientation.Vertical)
            for index, control in enumerate(config.platform_checks.values()):
                self.assertGreaterEqual(config.platform_table.rowHeight(index), control.sizeHint().height())
            self.assertLessEqual(panel.width(), 1024)
            self.assertTrue(panel.rect().contains(panel.prepare.rect().translated(panel.prepare.mapTo(panel, panel.prepare.rect().topLeft()))))

    def test_enlarged_map_text_reflows_existing_cards_without_overlap(self):
        panel = ManagerPanel(self.project())
        panel.configuration.goal_buttons['deliver'].click()
        for control in (*panel.platform_checks.values(), *panel.destination_checks.values()):
            control.setChecked(True)
        panel.resize(1280, 800); panel.show(); self.pump()
        canvas = panel.configuration.proposed_flow.canvas
        cards = {key: card for key, (card, _, _) in canvas.cards.items()}
        font = QFont(self.font); font.setPointSize(18); self.app.setFont(font); self.pump()
        for key, (card, _, _) in canvas.cards.items():
            self.assertIs(card, cards[key])
            self.assertGreaterEqual(card.height(), card.layout().totalHeightForWidth(card.width()))

    def test_heading_tracks_application_font_after_creation(self):
        title = HeadingLabel('Review your run')
        font = QFont(self.font); font.setPointSize(18); self.app.setFont(font); self.pump()
        self.assertAlmostEqual(title.font().pointSizeF(), 18 * 1.35)

    def test_output_refresh_preserves_selected_text_and_reading_position(self):
        view = RunOutputView(); view.resize(500, 250); view.show()
        view.append('test', '\n'.join('line ' + str(i) for i in range(100)), selected='test', keys={'test'})
        view.show_scope(selected='test', keys={'test'}); self.pump()
        cursor = view.log.textCursor(); cursor.setPosition(8); cursor.setPosition(18, QTextCursor.MoveMode.KeepAnchor)
        view.log.setTextCursor(cursor); view.log.verticalScrollBar().setValue(4)
        selected = view.log.textCursor().selectedText(); scroll = view.log.verticalScrollBar().value()
        view.show_scope(selected='test', keys={'test'})
        self.assertEqual(view.log.textCursor().selectedText(), selected)
        self.assertEqual(view.log.verticalScrollBar().value(), scroll)
        view.show_scope(selected='other', keys={'other'})
        self.assertFalse(view.log.textCursor().hasSelection())

    def test_first_live_output_does_not_include_empty_state_guidance(self):
        view = RunOutputView()
        view.show_scope(selected='test', keys={'test'})
        self.assertFalse(view.log.toPlainText())
        self.assertIn('No captured output', view.log.placeholderText())
        view.append('test', 'First real log line', selected='test', keys={'test'})
        self.assertEqual(view.log.toPlainText(), 'First real log line')

    def test_terminal_logs_distinguish_missing_empty_unreadable_and_truncated(self):
        from build_manager.diagnostics import EvidenceRead
        view = RunOutputView()
        for status, text, notice in (
                ('missing', '', 'log file is missing'),
                ('empty', '', 'log is empty'),
                ('unreadable', '', 'log could not be read'),
                ('truncated', 'First complete line', 'cause may appear later')):
            with self.subTest(status=status):
                from unittest.mock import Mock
                reader = Mock(return_value=EvidenceRead(text, status, status == 'truncated'))
                for _ in range(2):
                    view.show_scope(selected='test', keys={'test'}, reader=reader, reference='test.log', terminal=True)
                reader.assert_called_once_with('test')
                self.assertEqual(view.log.toPlainText(), text)
                self.assertIn(notice, view.notice.text())
        view.show_scope(selected='unrecorded', keys={'unrecorded'}, terminal=True)
        self.assertIn('No log was recorded', view.notice.text())

    def test_recipient_actions_and_release_notes_adapt_to_enlarged_text(self):
        from types import SimpleNamespace
        install_font_refresh(self.app)
        picker = RecipientPicker()
        picker.set_choices([dict(id='qa', label='QA phone')])
        fields = RunFieldsView(SimpleNamespace(run_fields=[dict(id='notes', label='Release notes',
            kind='multiline', destinations=['delivery'])]))
        fields.update_context('deliver', ['delivery'], '')
        fields.controls['notes'].setPlainText('Keep these notes')
        picker.resize(400, 500); picker.show(); fields.show(); self.pump()
        font = QFont(self.font); font.setPointSize(28); self.app.setFont(font); self.pump()
        self.assertEqual(picker.width(), 400)
        self.assertGreater(picker.reload.y(), picker.add.y())
        self.assertGreaterEqual(picker.manual.height(), picker.manual.fontMetrics().height() + 8)
        notes = fields.controls['notes']
        self.assertGreaterEqual(notes.viewport().height(), notes.fontMetrics().lineSpacing() * 3)
        self.assertEqual(notes.toPlainText(), 'Keep these notes')

    def test_native_entries_scale_when_created_late_and_shrink_on_reset(self):
        install_font_refresh(self.app)
        font = QFont(self.font); font.setPointSize(28); self.app.setFont(font); self.pump()
        dialog = QWidget(); form = QFormLayout(dialog)
        controls = (QLineEdit('Preserved'), QComboBox(), QSpinBox())
        controls[1].addItem('Current choice'); controls[2].setValue(42)
        for label, control in zip(('Text', 'Choice', 'Number'), controls):
            form.addRow(label, control)
        dialog.show(); self.pump()
        large = [control.height() for control in controls]
        for control in controls:
            self.assertGreaterEqual(control.height(), control.fontMetrics().height() + 8)
        number_editor = controls[2].findChild(QLineEdit)
        self.assertTrue(controls[2].rect().contains(number_editor.geometry()))
        font.setPointSize(12); self.app.setFont(font); self.pump()
        dialog.adjustSize(); self.pump()
        for control, height in zip(controls, large):
            self.assertLess(control.height(), height)
        self.assertEqual(controls[0].text(), 'Preserved')
        self.assertEqual(controls[1].currentText(), 'Current choice')
        self.assertEqual(controls[2].value(), 42)

    def test_account_method_inputs_and_storage_values_remain_specific(self):
        store = SettingsStore(self.root / 'private')
        dialog = AccountsDialog(store)
        self.assertFalse(dialog.form.isRowVisible(dialog.reference))
        self.assertFalse(dialog.form.isRowVisible(dialog.browse_button))
        dialog.kind.setCurrentIndex(dialog.kind.findData('environment-name'))
        self.assertTrue(dialog.form.isRowVisible(dialog.reference))
        self.assertFalse(dialog.form.isRowVisible(dialog.browse_button))
        dialog.name.setText('QA'); dialog.reference.setText('QA_GITHUB_TOKEN'); dialog.save()
        self.assertEqual(store.read()['accounts']['QA']['kind'], 'environment-name')
        self.assertEqual(store.read()['accounts']['QA']['reference'], 'QA_GITHUB_TOKEN')

    def test_machine_controls_do_not_probe_or_start_when_opened_or_switched(self):
        with patch('build_manager.vm_ui.VMWorker.start') as start:
            dialog = VMDialog()
            self.assertFalse(dialog.setup_section.toggle.isChecked())
            self.assertTrue(dialog.symlinks.isHidden())
            dialog.kind.setCurrentText('Windows')
            self.assertFalse(dialog.symlinks.isHidden())
            self.assertTrue(dialog.initializers['Linux'].isHidden())
            self.assertEqual(dialog.next_action_name, 'status')
            start.assert_not_called()


if __name__ == '__main__': unittest.main()
