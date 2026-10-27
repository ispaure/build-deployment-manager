"""Review attaches tasks without rebuilding the configuration's intent graph."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from build_manager import Phase, Plan
from build_manager.grouped_workflow import group_workflow, retained_proposal
from build_manager.proposed_workflow import propose
from test_journeys import integrated, CAPABILITY


class GroupedWorkflowTests(unittest.TestCase):
    def test_explicit_recipient_ids_keep_other_devices_out_of_selected_card(self):
        import json
        from build_manager.journeys import validate_plan
        with TemporaryDirectory() as directory:
            phases = [Phase('build', (sys.executable, '-V'), directory, effect='build', kind='build')]
            recipients = {}
            for device in ('boox-id', 'samsung-id'):
                ready, install = device + '.connect', device + '.install'
                phases += [Phase(ready, (sys.executable, '-V'), directory, effect='inspect', kind='connection', dependencies=('build',)),
                           Phase(install, (sys.executable, '-V'), directory, effect='deploy', approval_required=False, dependencies=('build', ready))]
                recipients[device] = dict(steps=[ready, install])
            plan = Plan('Fixture', 'devices', {}, tuple(phases), directory, journey=dict(schema=1, goal='deliver', platforms={},
                destinations={'devices':dict(identity='Selected Android devices', platforms=[], testing_optional=True,
                    steps=['boox-id.install', 'samsung-id.install'], recipients=recipients)}))
            capability = dict(schema=1, platforms=CAPABILITY['platforms'], destinations={'devices':dict(
                label='Android', platforms=['android'], testing_optional=True, approval_required=False, recipient_field='ids')})
            proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=[], destinations=['devices'], backends={},
                recipients={'ids':['NoteAir5C', 'SM-G955W']}, values={'ids':json.dumps(['boox-id','samsung-id'])})
            grouped = group_workflow(plan, capability, proposal)
            self.assertEqual(grouped.members['deliver.devices.0'], ('boox-id.connect', 'boox-id.install'))
            self.assertEqual(grouped.members['deliver.devices.1'], ('samsung-id.connect', 'samsung-id.install'))
            self.assertFalse(grouped.references['deliver.devices.0'])
            self.assertFalse(proposal.phases[-1].approval_required)
            validate_plan(plan)

    def test_overview_retains_identical_cards_edges_and_shared_preparation(self):
        with TemporaryDirectory() as directory:
            plan = integrated(Path(directory))
            before = plan.data()
            proposal = retained_proposal(plan, CAPABILITY)
            overview = group_workflow(plan, CAPABILITY, proposal)
            self.assertEqual(overview.phases, proposal.phases)
            self.assertEqual(overview.members['platform.android'], ('android',))
            self.assertEqual(overview.members['platform.ios'], ('ios',))
            self.assertIn('prepare', overview.members['prepare.firebase'])
            self.assertIn('prepare', overview.references['prepare.testflight'])
            keys = [key for members in overview.members.values() for key in members]
            self.assertCountEqual(keys + list(overview.unassigned), [phase.id for phase in plan.phases])
            self.assertEqual(plan.data(), before)

    def test_cross_platform_order_and_cleanup_stay_inside_original_cards(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plan = integrated(root)
            lifecycle = [Phase(f'ios-{index}', (sys.executable, '-V'), directory,
                dependencies=(f'ios-{index-1}',) if index else (), always=index % 2 == 1) for index in range(36)]
            admit = Phase('android-admit', (sys.executable, '-V'), directory, effect='inspect',
                          waits_for=('ios',), always=True)
            ios = replace(plan.phases[1], dependencies=('ios-35',))
            android = replace(plan.phases[0], dependencies=('android-admit',))
            plan = replace(plan, phases=(*lifecycle, ios, admit, android, *plan.phases[2:]))
            proposal = retained_proposal(plan, CAPABILITY)
            overview = group_workflow(plan, CAPABILITY, proposal)
            self.assertEqual(overview.phases, proposal.phases)
            self.assertEqual(len(overview.members['platform.ios']), 37)
            self.assertEqual(overview.members['platform.android'], ('android-admit', 'android'))
            self.assertFalse(any(node.id.startswith('step.') for node in overview.phases))
            self.assertEqual(len(overview.phases), len(proposal.phases))

    def test_legacy_interleaved_steps_remain_in_one_operation_card(self):
        with TemporaryDirectory() as directory:
            phases = (Phase('test-a', (sys.executable, '-V'), directory),
                Phase('inspect', (sys.executable, '-V'), directory, effect='inspect', dependencies=('test-a',)),
                Phase('test-b', (sys.executable, '-V'), directory, dependencies=('inspect',)))
            plan = Plan('Fixture', 'Inspect', {}, phases, directory)
            overview = group_workflow(plan)
            self.assertEqual([node.id for node in overview.phases], ['source', 'operation'])
            self.assertEqual(overview.members['operation'], tuple(phase.id for phase in phases))

    def test_recipient_cards_keep_names_without_guessing_action_identity(self):
        from copy import deepcopy
        with TemporaryDirectory() as directory:
            plan = integrated(Path(directory))
            capability = deepcopy(CAPABILITY)
            capability['destinations']['firebase']['recipient_field'] = 'people'
            proposal = propose(capability=capability, goal='deliver', revision='HEAD', platforms=['android', 'ios'],
                destinations=['firebase', 'testflight'], backends={}, recipients={'people': ['Tablet', 'Phone']})
            overview = group_workflow(plan, capability, proposal)
            self.assertEqual(overview.phases, proposal.phases)
            self.assertEqual(overview.members['deliver.firebase.0'], ('firebase',))
            self.assertEqual(overview.references['deliver.firebase.1'], ('firebase',))
            self.assertIn('did not declare', overview.notes['deliver.firebase.1'])
            self.assertFalse(overview.unassigned)

    def test_grouping_import_stays_free_of_qt(self):
        completed = subprocess.run([sys.executable, '-c',
            'import sys; import build_manager.grouped_workflow; assert not any(n.startswith(("PySide6", "PyQt")) for n in sys.modules)'], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
