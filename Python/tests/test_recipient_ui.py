"""Recipient choices, compact navigation and fitted maps remain read-only."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from build_manager.configuration_ui import ConfigurationView
from build_manager.recipient_ui import RecipientPicker
from build_manager.run_fields import selection_ids, validate_fields, validate_overrides
from build_manager.ui import ManagerPanel
from test_ui import OtherProject
from test_journeys import CAPABILITY


class RecipientUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app = QApplication.instance() or QApplication([])

    def project(self, root):
        project = OtherProject(root); project.journey_capability = deepcopy(CAPABILITY)
        project.journey_capability['destinations']['phones'] = dict(label='Android devices',platforms=['android'], category='Mobile dev devices', recipient_field='phones')
        project.run_fields = [dict(id='phones', label='Choose devices', kind='multiselect', destinations=['phones'])]
        project.run_defaults = lambda **_: {}
        project.run_choices = Mock(return_value={'phones':[dict(id='phone-1',label='Phone · saved'),dict(id='tablet-1',label='Tablet · saved')]})
        return project

    def test_selection_is_explicit_preserves_entered_ids_and_rejects_shell_or_duplicate_ids(self):
        picker = RecipientPicker()
        try:
            picker.set_choices([dict(id='phone-1',label='Phone')])
            self.assertEqual(picker.text(), '[]')
            picker.items.item(0).setCheckState(Qt.CheckState.Checked)
            picker.manual.setText('192.0.2.1:5555'); picker.add.click()
            self.assertEqual(selection_ids(picker.text()), ['phone-1','192.0.2.1:5555'])
            picker.set_choices([])
            self.assertEqual(selection_ids(picker.text()), ['phone-1','192.0.2.1:5555'])
            for value in ('["x", "x"]','["--all"]','["a; echo secret"]','"all"'):
                with self.assertRaises(ValueError):selection_ids(value)
        finally:picker.close()

    def test_short_delivery_labels_keep_counts_and_platform_navigation(self):
        with TemporaryDirectory() as directory:
            project = self.project(Path(directory))
            destinations = project.journey_capability['destinations']
            destinations['firebase']['category'] = 'Mobile tester platforms'
            destinations['testflight']['category'] = 'Mobile tester platforms'
            destinations['ios-device'] = dict(label='iOS devices', platforms=['ios'], category='Mobile dev devices')
            destinations['store'] = dict(label='Store upload', platforms=['ios'], category='Mobile stores')
            destinations['source'] = dict(label='Source release', platforms=[], category='Source releases')
            view = ConfigurationView(project)
            self.addCleanup(view.close)
            view.goal.setCurrentIndex(view.goal.findData('deliver'))
            view.destination_checks['firebase'].setChecked(True)
            view.destination_checks['testflight'].setChecked(True)
            self.assertEqual([view.delivery_tabs.tabText(i) for i in range(view.delivery_tabs.count())],
                             ['Tester (2)', 'Development (0)', 'Store (0)', 'Source (0)'])
            before = view.choices()
            for destination, category, platform in (
                    ('firebase', 'Mobile tester platforms', 'android'),
                    ('testflight', 'Mobile tester platforms', 'ios'),
                    ('phones', 'Mobile dev devices', 'android'),
                    ('ios-device', 'Mobile dev devices', 'ios')):
                view.open_section('delivery', destination)
                tabs = view.delivery_platform_tabs[category]
                page = view.delivery_platform_pages[category][platform][0]
                self.assertIs(tabs.currentWidget(), page)
                self.assertTrue(page.isAncestorOf(view.destination_checks[destination]))
                self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],
                                 ['Android (0)', 'iOS (0)'] if category == 'Mobile dev devices' else ['Android', 'iOS'])
            self.assertEqual(view.choices(), before)

    def test_development_counts_selected_devices_per_platform_and_total(self):
        with TemporaryDirectory() as directory:
            project = self.project(Path(directory))
            project.journey_capability['destinations']['ios-devices'] = dict(
                label='iOS devices', platforms=['ios'], category='Mobile dev devices', recipient_field='ios-phones')
            project.run_fields.append(dict(id='ios-phones', label='Choose iOS devices',
                                           kind='multiselect', destinations=['ios-devices']))
            view = ConfigurationView(project)
            self.addCleanup(view.close)
            view.goal.setCurrentIndex(view.goal.findData('deliver'))
            for destination in ('phones', 'ios-devices'):
                view.destination_checks[destination].setChecked(True)
            for field, prefix in (('phones', 'android'), ('ios-phones', 'ios')):
                picker = view.run_fields.controls[field]
                picker.set_choices([dict(id=f'{prefix}-{i}', label=f'Device {i}') for i in (1, 2)])
                for i in range(2):
                    picker.items.item(i).setCheckState(Qt.CheckState.Checked)
            category = 'Mobile dev devices'
            index = view.delivery_tabs.indexOf(view.delivery_categories[category][0])
            tabs = view.delivery_platform_tabs[category]
            self.assertEqual(view.delivery_tabs.tabText(index), 'Development (4)')
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Android (2)', 'iOS (2)'])
            view.destination_checks['ios-devices'].setChecked(False)
            self.assertEqual(view.delivery_tabs.tabText(index), 'Development (2)')
            self.assertEqual(tabs.tabText(1), 'iOS (0)')
            view.destination_checks['ios-devices'].setChecked(True)
            self.assertEqual(view.delivery_tabs.tabText(index), 'Development (4)')
            view.run_fields.controls['phones'].items.item(1).setCheckState(Qt.CheckState.Unchecked)
            self.assertEqual(tabs.tabText(0), 'Android (1)')
            self.assertEqual(view.delivery_tabs.tabText(index), 'Development (3)')
            view.goal.setCurrentIndex(view.goal.findData('validate'))
            self.assertEqual(view.delivery_tabs.tabText(index), 'Development (0)')

    def test_recipient_controls_live_under_delivery_category_and_map_tracks_selected_names(self):
        with TemporaryDirectory() as directory:
            view = ConfigurationView(self.project(Path(directory)))
            try:
                view.goal.setCurrentIndex(view.goal.findData('deliver'))
                view.platform_checks['android'].setChecked(True); view.destination_checks['phones'].setChecked(True)
                picker = view.run_fields.controls['phones']
                view.run_fields.choice_results.put(({'phones':[dict(id='phone-1',label='Phone · saved')]},None))
                view.run_fields.choices_loaded()
                self.assertIn('Choose at least one', view.run_fields.missing_selection())
                picker.items.item(0).setCheckState(Qt.CheckState.Checked)
                self.assertEqual(view.run_fields.values()['phones'], '["phone-1"]')
                self.assertFalse(view.run_fields.missing_selection())
                nodes = {row.id: row for row in view.current_proposal.phases}
                self.assertEqual(nodes['deliver.phones.0'].label, 'Phone')
                view.proposed_flow.select('deliver.phones.0')
                self.assertIs(view.config_tabs.currentWidget(), view.config_pages['delivery'])
                self.assertIs(view.delivery_tabs.currentWidget(), view.delivery_categories['Mobile dev devices'][0])
                view.destination_checks['phones'].setChecked(False)
                self.assertNotIn('phones', view.run_fields.values())
                self.assertEqual(picker.text(), '["phone-1"]')
            finally:view.run_fields.stop();view.close()

    def test_platform_table_and_fit_map_contain_every_card_after_resize(self):
        with TemporaryDirectory() as directory:
            view = ConfigurationView(self.project(Path(directory)))
            view.resize(1100, 700); view.show()
            try:
                view.platform_checks['android'].setChecked(True); view.platform_checks['ios'].setChecked(True)
                self.assertEqual(view.platform_table.rowCount(), 2)
                self.assertIs(view.platform_table.cellWidget(0, 0), view.platform_checks['android'])
                self.assertIs(view.platform_table.cellWidget(0, 1), view.platform_backends['android'])
                for width in (1100, 850):
                    view.resize(width,700)
                    for _ in range(4):self.app.processEvents()
                    flow = view.proposed_flow; flow.fit_button.click()
                    self.app.processEvents()
                    self.assertGreaterEqual(flow.scroll.transform().m11(), flow.scroll.minimum_scale)
                    self.assertEqual(flow.scroll.horizontalScrollBar().maximum(), 0)
                    self.assertEqual(flow.scroll.verticalScrollBar().maximum(), 0)
                    self.assertTrue(all(card[1].isHidden() for card in flow.canvas.cards.values()))
            finally:view.run_fields.stop();view.close()

    def test_invalid_recipient_field_cannot_be_advertised_and_selections_are_validated(self):
        with TemporaryDirectory() as directory:
            project = self.project(Path(directory))
            validate_fields(project.run_fields, {'operations':['Test']}, project.journey_capability)
            with self.assertRaises(ValueError):validate_fields([], {'operations':['Test']}, project.journey_capability)
            with self.assertRaises(ValueError):validate_overrides(project.run_fields, {'phones':'all devices'})
            self.assertEqual(validate_overrides(project.run_fields, {'phones':'["phone-1"]'}), {'phones':'["phone-1"]'})

    def test_missing_device_selection_stops_before_preparing_plan(self):
        with TemporaryDirectory() as directory:
            project = self.project(Path(directory)); project.make_journey = Mock()
            panel = ManagerPanel(project)
            try:
                panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
                panel.platform_checks['android'].setChecked(True);panel.destination_checks['phones'].setChecked(True)
                panel.inspect_plan(); project.make_journey.assert_not_called()
                self.assertIn('Choose at least one', panel.plan_feedback.text())
                self.assertIs(panel.configuration.config_tabs.currentWidget(), panel.configuration.config_pages['delivery'])
            finally:panel.close()

    def test_project_bridge_uses_advertised_dynamic_inputs_in_project_process(self):
        from build_manager.bridge import ProjectBridge
        bridge = ProjectBridge.__new__(ProjectBridge)
        bridge.descriptor = {'dynamic_run_inputs':True}
        bridge.run_fields = [dict(id='phones',kind='multiselect')]
        bridge.call = Mock(return_value={})
        bridge.run_defaults(); bridge.run_choices()
        self.assertEqual([call.args[0] for call in bridge.call.call_args_list], ['run_defaults','run_choices'])
