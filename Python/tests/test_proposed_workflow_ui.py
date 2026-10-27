"""Live intent sketches never prepare a plan, and cards reveal the owning settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from build_manager.proposed_workflow import propose
from build_manager.ui import ManagerPanel
from test_ui import OtherProject
from test_journeys import CAPABILITY, integrated


class ProposedWorkflowTests(unittest.TestCase):
    def test_device_only_proposal_has_build_without_missing_test_platform_blockers(self):
        capability = deepcopy(CAPABILITY)
        capability['destinations']['device'] = dict(label='Device', platforms=['android'], testing_optional=True)
        proposal = propose(capability=capability, goal='deliver', revision='HEAD',
            platforms=[], destinations=['device'], backends={})
        self.assertFalse(proposal.blockers)
        nodes = {node.id: node for node in proposal.phases}
        self.assertNotIn('choose-platforms', nodes)
        self.assertNotIn('missing.android', nodes)
        self.assertEqual(nodes['prepare.device'].dependencies, ('source',))

    def test_optional_testing_package_keeps_source_or_selected_checks_as_input(self):
        capability = deepcopy(CAPABILITY)
        capability['packages'] = {
            'debug': dict(label='Build Android Debug APK', platforms=['android']),
        }
        capability['destinations']['device'] = dict(
            label='Device', platforms=['android'], testing_optional=True, package='debug')
        for platforms, expected in (([], ('source',)), (['android'], ('platform.android',)),
                                    (['ios'], ('source',)), (['ios', 'android'], ('platform.android',))):
            with self.subTest(platforms=platforms):
                proposal = propose(capability=capability, goal='deliver', revision='working-tree',
                    platforms=platforms, destinations=['device'], backends={})
                nodes = {node.id: node for node in proposal.phases}
                self.assertFalse(proposal.blockers)
                self.assertEqual(nodes['package.debug'].dependencies, expected)
                self.assertEqual(nodes['deliver.device'].dependencies, ('package.debug',))

    def test_optional_testing_package_chain_starts_at_source(self):
        capability = deepcopy(CAPABILITY)
        capability['packages'] = {
            'debug': dict(label='Build Android Debug APK', platforms=['android']),
            'bundle': dict(label='Bundle', platforms=['android'], dependencies=['debug']),
        }
        capability['destinations']['device'] = dict(
            label='Device', platforms=['android'], testing_optional=True, package='bundle')
        proposal = propose(capability=capability, goal='deliver', revision='HEAD',
            platforms=[], destinations=['device'], backends={})
        nodes = {node.id: node for node in proposal.phases}
        self.assertEqual(nodes['package.debug'].dependencies, ('source',))
        self.assertEqual(nodes['package.bundle'].dependencies, ('package.debug',))

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, root):
        project = OtherProject(root)
        project.journey_capability = deepcopy(CAPABILITY)
        project.journey_capability['selectable_backends'] = True
        project.backend_options = lambda *_: ('Local', 'GitHub')
        project.make_journey = Mock(side_effect=AssertionError('Editing must not prepare a project plan'))
        project.make_plan = Mock(side_effect=AssertionError('Editing must not prepare a project plan'))
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        return panel

    def test_proposal_is_non_executable_and_keeps_missing_requirements_visible(self):
        before = deepcopy(CAPABILITY)
        proposal = propose(capability=CAPABILITY, goal='deliver', revision='working-tree',
            platforms=['ios'], destinations=['firebase'], backends={'ios': 'Local'})
        nodes = {node.id: node for node in proposal.phases}
        self.assertTrue(proposal.proposed)
        self.assertTrue(nodes['missing.android'].issue)
        self.assertIn('missing.android', nodes['prepare.firebase'].dependencies)
        self.assertNotIn('platform.ios', nodes['prepare.firebase'].dependencies)
        self.assertEqual(nodes['deliver.firebase'].dependencies, ('prepare.firebase',))
        self.assertFalse(hasattr(proposal, 'save'))
        self.assertTrue(all(not hasattr(node, 'argv') for node in proposal.phases))
        self.assertEqual(CAPABILITY, before)
        self.assertFalse(any('committed source' in message for message in proposal.messages))

    def test_empty_and_checks_only_maps_never_show_delivery(self):
        args = dict(capability=CAPABILITY, goal='validate', revision='HEAD',
                    platforms=[], destinations=[], backends={})
        self.assertEqual([node.id for node in propose(**args).phases], ['source', 'choose-platforms'])
        args['platforms'] = ['android', 'ios']
        proposal = propose(**args)
        nodes = {node.id: node for node in proposal.phases}
        self.assertEqual(nodes['platform.ios'].dependencies, ('source',))
        self.assertEqual(nodes['platform.android'].dependencies, ('source',))
        self.assertFalse(any(key.startswith('deliver.') for key in nodes))

    def test_editing_updates_branches_without_planning_and_retains_conflicting_choices(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            self.assertIn('choose-platforms', view.proposed_flow.canvas.cards)
            self.assertFalse(panel.start.isEnabled())
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['ios'].setChecked(True)
            panel.destination_checks['firebase'].setChecked(True)
            self.assertIn('missing.android', view.proposed_flow.canvas.cards)
            self.assertTrue(panel.destination_checks['firebase'].isChecked())
            self.assertFalse(panel.platform_checks['android'].isChecked())
            panel.platform_checks['android'].setChecked(True)
            self.assertNotIn('missing.android', view.proposed_flow.canvas.cards)
            self.assertIn('prepare.firebase', view.proposed_flow.canvas.cards)
            panel.destination_checks['firebase'].setChecked(False)
            self.assertNotIn('deliver.firebase', view.proposed_flow.canvas.cards)
            self.assertTrue(view.proposed_flow.plan.proposed)
            self.assertIn('Proposed', view.proposed_flow.canvas.cards['source'][1].text())
            panel.project.make_journey.assert_not_called()
            panel.project.make_plan.assert_not_called()
            self.assertIsNone(panel.plan)

    def test_cards_open_the_matching_section_without_changing_choices(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['ios'].setChecked(True)
            panel.destination_checks['testflight'].setChecked(True)
            before = panel.choices()
            view.sections['delivery'].toggle.setChecked(False)
            view.proposed_flow.canvas.cards['deliver.testflight'][0].click()
            self.assertTrue(view.sections['delivery'].toggle.isChecked())
            self.assertEqual(view.last_opened_section, 'delivery')
            view.sections['source'].toggle.setChecked(False)
            QTest.keyClick(view.proposed_flow.canvas.cards['source'][0], Qt.Key.Key_Space)
            self.assertTrue(view.sections['source'].toggle.isChecked())
            self.assertEqual(view.last_opened_section, 'source')
            view.sections['platforms'].toggle.setChecked(False)
            view.proposed_flow.canvas.cards['platform.ios'][0].click()
            self.assertTrue(view.sections['platforms'].toggle.isChecked())
            self.assertEqual(panel.choices(), before)
            panel.project.make_journey.assert_not_called()

    def test_source_is_explicit_round_trips_legacy_values_and_cannot_change_while_busy(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.platform_checks['ios'].setChecked(True)
            panel.platform_backends['ios'].setCurrentText('GitHub')
            self.assertEqual(panel.revision.text(), 'working-tree')
            self.assertIn('Choose Latest commit', view.readiness.text())
            view.proposed_flow.canvas.cards['source'][0].click()
            view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
            self.assertIn('uncommitted edits are excluded', view.source_mode.toolTip())
            self.assertEqual(panel.choices()['revision'], 'HEAD')
            self.assertIn('excludes edits', view.current_proposal.phases[0].description)
            panel.revision.setText('v2.0-alpha')
            self.assertEqual(view.source_mode.currentData(), 'custom')
            self.assertFalse(panel.revision.isHidden())
            view.source_mode.setCurrentIndex(view.source_mode.findData('working-tree'))
            self.assertEqual(panel.choices()['revision'], 'working-tree')
            panel.set_busy(True)
            self.assertFalse(view.source_mode.isEnabled())
            panel.set_busy(False)
            self.assertTrue(view.source_mode.isEnabled())
            self.assertFalse(view.require_validation.isEnabled())
            self.assertTrue(view.require_validation.isChecked())

    def test_valid_choices_stay_quiet_and_source_conflicts_resolve_in_place(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.project.journey_capability['destinations']['testflight']['source_policy'] = 'committed'
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['ios'].setChecked(True)
            panel.destination_checks['testflight'].setChecked(True)
            self.assertIn('source', view.blocker_actions)
            view.blocker_actions['source'].click()
            self.assertFalse(view.source_summary.isHidden())
            self.assertIn('Choose Latest commit', view.source_summary.text())
            view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
            self.assertNotIn('source', view.blocker_actions)
            self.assertTrue(view.source_summary.isHidden())
            self.assertTrue(view.readiness.isHidden())
            self.assertEqual(view.current_proposal.messages, ())
            self.assertEqual(panel.status.text(), '')
            view.proposed_flow.canvas.cards['source'][0].click()
            self.assertEqual(view.last_opened_section, 'source')
            self.assertTrue(view.source_summary.isHidden())
            panel.project.make_journey.assert_not_called()

    def test_clean_checkout_policy_is_available_without_a_speculative_warning(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.project.journey_capability['destinations']['testflight']['source_policy'] = 'clean-checkout'
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['ios'].setChecked(True)
            panel.destination_checks['testflight'].setChecked(True)
            view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
            self.assertNotIn('source', view.blocker_actions)
            self.assertTrue(view.source_summary.isHidden())
            self.assertTrue(view.readiness.isHidden())
            self.assertIn('clean checkout', view.source_mode.toolTip())
            help_text = view.source_mode.toolTip()
            view.refresh_proposal(); view.refresh_proposal()
            self.assertEqual(view.source_mode.toolTip(), help_text)
            view.source_mode.setCurrentIndex(view.source_mode.findData('working-tree'))
            self.assertFalse(view.source_summary.isHidden())
            self.assertIn('source', view.blocker_actions)

    def test_custom_revision_typing_does_not_hide_field_at_head_prefix_and_empty_source_is_local_error(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.resize(1100, 800); panel.show(); self.app.processEvents()
            view.source_mode.setCurrentIndex(view.source_mode.findData('custom'))
            panel.revision.setFocus()
            self.app.processEvents()
            QTest.keyClicks(panel.revision, 'HEAD~2')
            self.assertEqual(panel.revision.text(), 'HEAD~2')
            self.assertEqual(view.source_mode.currentData(), 'custom')
            self.assertFalse(panel.revision.isHidden())
            panel.revision.clear()
            panel.inspect_plan()
            self.assertIn('Choose a source revision', panel.plan_feedback.text())
            self.assertFalse(panel.preparing)
            panel.project.make_journey.assert_not_called()
            panel.project.make_plan.assert_not_called()

    def test_review_replaces_proposal_with_exact_plan_and_back_preserves_configuration(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            for item in panel.platform_checks.values():
                item.setChecked(True)
            for item in panel.destination_checks.values():
                item.setChecked(True)
            view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
            plan = integrated(Path(directory))
            plan = replace(plan, journey=dict(plan.journey,
                executions={name: dict(backend='Local', steps=[]) for name in ('android', 'ios')}))
            panel.project.make_journey.side_effect = None
            panel.project.make_journey.return_value = plan
            panel.inspect_plan()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005)
                self.assertLess(time.monotonic(), deadline)
            self.assertEqual(panel.stages.currentIndex(), 1)
            self.assertFalse(getattr(panel.review_flow.plan, 'proposed', False))
            self.assertIn('Prepared plan', panel.review_flow.legend.text())
            self.assertIn('Planned', panel.review_flow.canvas.cards['prepare'][1].text())
            panel.project.make_journey.assert_called_once()
            self.assertEqual(panel.project.make_journey.call_args.kwargs['revision'], 'HEAD')
            panel.back.click()
            self.assertEqual(panel.stages.currentIndex(), 0)
            self.assertTrue(view.proposed_flow.plan.proposed)
            self.assertEqual(view.source_mode.currentData(), 'HEAD')
            self.assertFalse((Path(directory) / 'package.bin').exists())

    def test_source_policy_failure_reveals_source_without_silently_switching_it(self):
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.goal.setCurrentIndex(panel.goal.findData('deliver'))
            panel.platform_checks['android'].setChecked(True)
            panel.destination_checks['firebase'].setChecked(True)
            panel.project.make_journey.side_effect = ValueError('Delivery requires committed source.')
            view.sections['source'].toggle.setChecked(False)
            panel.inspect_plan()
            deadline = time.monotonic() + 5
            while panel.preparing:
                self.app.processEvents(); time.sleep(.005)
                self.assertLess(time.monotonic(), deadline)
            self.assertEqual(panel.stages.currentIndex(), 0)
            self.assertTrue(view.sections['source'].toggle.isChecked())
            self.assertEqual(panel.revision.text(), 'working-tree')
            self.assertIn('Choose Latest commit', view.source_summary.text())
            self.assertIsNone(panel.plan)

    def test_long_proposed_card_labels_fit_and_source_choices_preserve_custom_revision(self):
        from PySide6.QtWidgets import QLabel
        with TemporaryDirectory() as directory:
            panel = self.panel(Path(directory)); view = panel.configuration
            panel.project.journey_capability['platforms']['ios']['label'] = 'A long platform label that wraps across several readable lines'
            panel.platform_checks['ios'].setChecked(True)
            panel.resize(1100, 800); panel.show(); self.app.processEvents()
            card = view.proposed_flow.canvas.cards['platform.ios'][0]
            self.assertGreaterEqual(card.height(), card.layout().totalHeightForWidth(card.width()))
            for label in card.findChildren(QLabel):
                if not label.isHidden():
                    self.assertLessEqual(label.geometry().bottom(), card.height())
            panel.revision.setText('v3.1-preview')
            view.source_mode.setCurrentIndex(view.source_mode.findData('HEAD'))
            view.source_mode.setCurrentIndex(view.source_mode.findData('custom'))
            self.assertEqual(panel.revision.text(), 'v3.1-preview')
