"""Declared artifact DAGs show real sharing and keep build variants separate."""
from copy import deepcopy
import unittest
from build_manager.journeys import validate_capability
from build_manager.proposed_workflow import propose
from build_manager.run_fields import validate_fields, validate_overrides

CAPABILITIES = dict(platforms=['ios'], operations=['Test'])
CAPABILITY = dict(schema=1, platforms={'ios':dict(operation='Test', backend='Local')}, packages={
    'release':dict(label='Build Release', stage='build', platforms=['ios']),
    'store':dict(label='Sign for TestFlight', stage='package', platforms=['ios'], dependencies=['release']),
    'device':dict(label='Sign for devices', stage='package', platforms=['ios'], dependencies=['release']),
    'debug':dict(label='Build Debug', stage='build', platforms=['ios'])}, destinations={
    'testflight':dict(label='TestFlight', platforms=['ios'], package='store'),
    'devices':dict(label='Devices', platforms=['ios'], package_field='variant', package_default='debug',
                   package_variants={'debug':'debug','release':'device'})})
FIELD = dict(id='variant', label='Device package', kind='choice', default='debug',
             options={'debug':'Debug','release':'Release'}, destinations=['devices'])


class PackageWorkflowTests(unittest.TestCase):
    def test_optional_builds_use_only_their_platform_checks_and_inherit_package_gates(self):
        capability = deepcopy(CAPABILITY)
        capability['platforms']['windows'] = dict(operation='Test', backend='VM')
        capability['destinations']['devices']['testing_optional'] = True
        for selected, expected in ((['windows'], ('source',)),
                                   (['windows', 'ios'], ('platform.ios',))):
            proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=selected,
                destinations=['devices'], backends={})
            nodes = {p.id: p for p in proposal.phases}
            self.assertEqual(nodes['package.debug'].dependencies, expected)
            self.assertEqual(nodes['platform.windows'].dependencies, ('source',))
            self.assertFalse(proposal.blockers)
        proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=['ios', 'windows'],
            destinations=['devices'], backends={}, values={'variant': 'release'})
        nodes = {p.id: p for p in proposal.phases}
        self.assertEqual(nodes['package.release'].dependencies, ('platform.ios',))
        self.assertEqual(nodes['package.device'].dependencies, ('package.release',))

    def test_shared_package_keeps_required_gates_in_both_destination_orders(self):
        capability = deepcopy(CAPABILITY)
        capability['destinations']['devices'].update(testing_optional=True, package='store')
        capability['destinations']['devices'].pop('package_variants')
        for destinations in (['devices', 'testflight'], ['testflight', 'devices']):
            proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=[],
                destinations=destinations, backends={})
            nodes = {p.id: p for p in proposal.phases}
            self.assertEqual(nodes['package.release'].dependencies, ('missing.ios',))
            self.assertEqual(nodes['package.store'].dependencies, ('package.release',))
            self.assertTrue(nodes['package.release'].issue)
            self.assertEqual(sum(p.id == 'package.release' for p in proposal.phases), 1)

    def proposal(self, **kwargs):
        return propose(capability=CAPABILITY, goal='deliver', revision='HEAD', platforms=['ios'],
                       destinations=['testflight','devices'], backends={}, **kwargs)

    def test_release_archive_is_shared_and_exports_remain_distinct(self):
        validate_capability(CAPABILITY, CAPABILITIES)
        validate_fields([FIELD], CAPABILITIES, CAPABILITY)
        proposal = self.proposal(values={'variant':'release'})
        nodes = {p.id:p for p in proposal.phases}
        self.assertEqual(sum(p.id == 'package.release' for p in proposal.phases), 1)
        self.assertNotIn('package.debug', nodes)
        for key in ('store','device'):self.assertIn('package.release', nodes['package.'+key].dependencies)
        self.assertEqual(nodes['deliver.devices'].dependencies, ('package.device',))
        self.assertEqual(nodes['deliver.testflight'].dependencies, ('package.store',))

    def test_default_debug_does_not_claim_release_reuse(self):
        nodes = {p.id:p for p in self.proposal().phases}
        self.assertIn('package.debug', nodes)
        self.assertNotIn('package.device', nodes)
        self.assertNotIn('package.release', nodes['package.debug'].dependencies)

    def test_malformed_package_edges_and_unknown_variants_are_rejected(self):
        for parent in ('missing','store'):
            value = deepcopy(CAPABILITY); value['packages']['release']['dependencies'] = [parent]
            with self.assertRaises(ValueError):validate_capability(value, CAPABILITIES)
        with self.assertRaises(ValueError):validate_overrides([FIELD], {'variant':'wrong'})
        self.assertEqual(validate_overrides([FIELD], {'variant':'release'}), {'variant':'release'})

    def test_choice_widget_forwards_keys_and_remembers_selection(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from build_manager.run_fields_ui import RunFieldsView
        class Project:run_fields=[FIELD]
        app = QApplication.instance() or QApplication([])
        view = RunFieldsView(Project())
        try:
            view.update_context('deliver', ['devices'], '')
            self.assertEqual(view.values(), {'variant':'debug'})
            view.controls['variant'].setText('release')
            self.assertEqual(view.saved_values(), {'variant':'release'})
            view.update_context('validate', [], '')
            self.assertEqual(view.values(), {})
            view.update_context('deliver', ['devices'], '')
            self.assertEqual(view.values(), {'variant':'release'})
        finally:view.stop(); view.close()

    def test_later_single_delivery_stays_aligned_with_its_parent(self):
        from types import SimpleNamespace
        from build_manager.workflow_ui import layout_positions
        def step(key, parents=()):return SimpleNamespace(id=key, dependencies=parents)
        steps = [step('source'), step('ios', ('source',)), step('android', ('source',)),
                 step('export', ('ios',)), step('devices', ('android',)), step('upload', ('export',))]
        positions = layout_positions(steps)
        self.assertEqual(positions['upload'][1], positions['export'][1])
        self.assertLess(positions['upload'][1], positions['devices'][1])

    def test_captured_release_packages_stay_unblocked_and_hosted_execution_requires_commit(self):
        for backend in ('Local', 'GitHub'):
            capability = deepcopy(CAPABILITY)
            capability['platforms']['ios']['backend'] = backend
            proposal = propose(capability=capability, goal='deliver', revision='working-tree',
                platforms=['ios'], destinations=['testflight','devices'], backends={}, values={'variant':'release'})
            self.assertEqual('source' in {b.id for b in proposal.blockers}, backend == 'GitHub')
            self.assertFalse(any('Delivery policy may require' in m for m in proposal.messages))
            if backend == 'Local':
                self.assertEqual(proposal.messages, ())

    def test_headings_group_delivery_columns_and_source_rules_explain_selected_destinations(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from build_manager.workflow_ui import FlowCanvas
        app = QApplication.instance() or QApplication([])
        capability = deepcopy(CAPABILITY)
        capability['destinations']['testflight']['source_policy'] = 'committed'
        proposal = propose(capability=capability, goal='deliver', revision='working-tree', platforms=['ios'],
                           destinations=['testflight'], backends={})
        self.assertTrue(any('TestFlight requires committed source' in message for message in proposal.messages))
        canvas = FlowCanvas()
        try:
            canvas.reset(proposal)
            self.assertEqual([header.text() for header in canvas.headers], ['Source','Testing','Delivery'])
        finally:canvas.close()
        capability['destinations']['testflight']['source_policy'] = 'clean-checkout'
        proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=['ios'],
                           destinations=['testflight'], backends={})
        self.assertTrue(any('clean checkout' in message for message in proposal.messages))
