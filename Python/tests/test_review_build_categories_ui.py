"""The live review map classifies actual work and declared retained provenance."""
from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QLabel

from build_manager import Phase, Plan
from build_manager.proposed_workflow import propose
from build_manager.review_presentation import prepare_review_data
from build_manager.review_ui import ReviewPlanView
from build_manager.workflow_ui import WorkflowGraphView
from test_journeys import CAPABILITY, integrated


class ReviewBuildCategoriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ReviewPlanView()
        self.addCleanup(self.view.close)
        self.root = Path.cwd()

    def phase(self, key, **options):
        return Phase(key, (sys.executable, '-V'), str(self.root), **options)

    def plan(self, phases, **options):
        return Plan('Fixture', 'Project operation', {'commit': 'captured'}, tuple(phases), str(self.root), **options)

    def show_plan(self, plan, **options):
        prepared = prepare_review_data(plan, **options)
        self.view.reset(prepared.plan, prepared=prepared)
        return prepared

    def test_mixed_project_operation_keeps_checks_build_and_delivery_distinct(self):
        phases = [
            self.phase('checks', effect='test'),
            self.phase('package', effect='build', section='delivery', dependencies=('checks',),
                       artifacts=('out/declared-release.zip',)),
            self.phase('inspection', effect='test', dependencies=('package',)),
            self.phase('upload', effect='upload', dependencies=('inspection',)),
        ]
        plan = self.plan(phases, effect='build', adapter={'platform': 'blender'})
        original = plan.data()
        data = self.show_plan(plan)
        nodes = {node.category: node for node in data.grouped.phases if node.category}
        headers = {header.text() for header in self.view.flow.canvas.headers}
        self.assertEqual(headers, {'Source', 'Testing', 'Build & Package', 'Delivery'})
        build, delivery = nodes['build'], nodes['delivery']
        self.assertEqual(data.grouped.members[build.id], ('package',))
        self.assertEqual(data.grouped.members[delivery.id], ('upload',))
        self.assertEqual([node.category for node in data.grouped.phases], ['', 'platforms', 'build', 'platforms', 'delivery'])
        self.assertIn('blender', build.description)
        self.assertIn('declared-release.zip', build.description)
        self.assertIsNotNone(self.view.flow.canvas.cards[delivery.id][0].findChild(QLabel, 'approvalBadge'))
        self.view.flow.canvas.cards[build.id][0].click()
        self.assertEqual(self.view.flow.pages.currentIndex(), 0)
        self.assertEqual(self.view.selected, 'package')
        self.assertIn('declared-release.zip', self.view.fact_values['Outputs'].text())
        self.assertEqual(plan.data(), original)

    def test_checks_only_and_undeclared_artifact_names_do_not_imply_build_or_reuse(self):
        plan = self.plan([self.phase('checks', effect='test', artifacts=('reports/looks-like-package.zip',))],
                         settings={'retained_delivery': {'description': 'no original run identity'}})
        data = self.show_plan(plan)
        self.assertEqual({header.text() for header in self.view.flow.canvas.headers}, {'Source', 'Testing'})
        self.assertFalse(any(node.category == 'build' for node in data.grouped.phases))

    def test_actual_journey_build_replaces_the_generic_preparation_category(self):
        plan = integrated(self.root)
        data = self.show_plan(plan, capability=CAPABILITY)
        nodes = {node.id: node for node in data.grouped.phases}
        for name in ('firebase', 'testflight'):
            package = nodes['prepare.' + name]
            category, description = data.grouped.card_details[package.id]
            self.assertEqual(category, 'build')
            self.assertIn('package.bin', description)
            self.assertIn('package.bin', self.view.flow.canvas.cards[package.id][0].toolTip())
            self.assertIn(package.id, nodes['deliver.' + name].dependencies)
        self.assertEqual(set(self.view.rows), {phase.id for phase in plan.phases})

    def test_journey_with_no_build_omits_even_declared_package_from_resolved_map(self):
        plan = integrated(self.root)
        phases = tuple(replace(phase, dependencies=('android', 'ios'))
                       if phase.effect == 'upload' else phase for phase in plan.phases if phase.id != 'prepare')
        plan = replace(plan, phases=phases)
        capability = {**CAPABILITY, 'packages': {'apk': dict(label='Export APK', stage='package', platforms=['android'])},
                      'destinations': {**CAPABILITY['destinations'],
                                       'firebase': {**CAPABILITY['destinations']['firebase'], 'package': 'apk'}}}
        data = self.show_plan(plan, capability=capability)
        self.assertFalse(any('Build & Package' in header.text() for header in self.view.flow.canvas.headers))
        self.assertNotIn('package.apk', data.grouped.members)
        self.assertIn('platform.android', next(node for node in data.grouped.phases
                                               if node.id == 'deliver.firebase').dependencies)
        self.assertEqual(set(self.view.rows), {phase.id for phase in phases})

    def test_explicit_retained_provenance_labels_reuse_without_inventing_outputs(self):
        plan = self.plan([self.phase('verify', effect='inspect'),
                          self.phase('install', effect='deploy', dependencies=('verify',))],
                         settings={'retained_delivery': dict(original_run='/fixture/saved',
                             original_plan_identity='captured-plan', recipients={'android': ['device']})})
        data = self.show_plan(plan)
        node = next(node for node in data.grouped.phases if node.category == 'build')
        self.assertEqual(node.label, 'Reuse retained artifacts')
        self.assertEqual(data.grouped.members[node.id], ())
        self.assertNotIn('Declared outputs', node.description)
        self.view.flow.canvas.cards[node.id][0].click()
        self.assertIn('Reuse verified artifacts', self.view.context_info.text())
        self.assertIn('android', self.view.context_info.text())
        self.assertEqual(self.view.flow.pages.currentIndex(), 0)

        prepare = self.phase('prepare', effect='build', artifacts=('outputs/exported.apk',))
        plan = replace(plan, phases=(prepare, replace(plan.phases[-1], dependencies=('prepare',))))
        data = self.show_plan(plan)
        node = next(node for node in data.grouped.phases if node.category == 'build')
        self.view.flow.canvas.cards[node.id][0].click()
        self.assertEqual(self.view.selected, 'prepare')
        self.assertIn('Uses verified artifacts', self.view.fact_values['Notes'].text())
        self.assertIn('exported.apk', self.view.fact_values['Outputs'].text())

    def test_proposal_marks_only_build_goal_and_declared_package_stage(self):
        workflow = WorkflowGraphView()
        self.addCleanup(workflow.close)
        args = dict(revision='HEAD', platforms=['android'], destinations=['firebase'], backends={})
        workflow.reset(propose(capability=CAPABILITY, goal='deliver', **args))
        self.assertFalse(any('Build & Package' in header.text() for header in workflow.canvas.headers))
        capability = {**CAPABILITY, 'packages': {'apk': dict(label='Export APK', stage='package', platforms=['android'])},
                      'destinations': {**CAPABILITY['destinations'],
                                       'firebase': {**CAPABILITY['destinations']['firebase'], 'package': 'apk'}}}
        proposal = propose(capability=capability, goal='deliver', **args)
        package = next(node for node in proposal.phases if node.id == 'package.apk')
        self.assertEqual(package.section, 'delivery')
        self.assertEqual(package.category, 'build')
        workflow.reset(proposal)
        self.assertIn('Build & Package', {header.text() for header in workflow.canvas.headers})
        workflow.reset(propose(capability=None, goal='build', platform='android', **args))
        self.assertIn('Build & Package', {header.text() for header in workflow.canvas.headers})
