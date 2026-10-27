"""Start authorizes tester uploads without weakening evidence or recovery gates."""
from dataclasses import replace
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch

from build_manager import Executor, Phase, Plan
from build_manager.plan_summary import start_scope, summary_rows
from build_manager.workflows import start_authorized_effects
from build_manager.ui import ManagerPanel
from test_journeys import integrated
import test_ui as fixtures
from test_ui import OtherProject


class StartUploadTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ManagerUITests.setUpClass.__func__)
    setUp = fixtures.ManagerUITests.setUp
    inspect = fixtures.ManagerUITests.inspect
    finish = fixtures.ManagerUITests.finish

    def test_gui_start_runs_both_uploads_without_a_second_approval(self):
        original = integrated(self.root)
        project = OtherProject(self.root)
        project.make_plan = lambda *args, **kwargs: original
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        panel.goal.setCurrentIndex(panel.goal.findData('advanced'))
        self.inspect(panel)
        self.assertTrue(all(not phase.approval_required for phase in panel.plan.phases[-2:]))
        self.assertTrue(all(phase.approval_required for phase in original.phases[-2:]))
        self.assertIn('Start authorizes', panel.review_help.text())
        self.assertIn('Start authorizes', panel.start.toolTip())
        self.assertNotIn('separate approval', '\n'.join(row['detail'] for row in summary_rows(panel.plan)[1]))
        with patch.object(panel, 'confirm_continuation', side_effect=AssertionError('second approval')), \
                patch('build_manager.ui.QMessageBox.question', side_effect=AssertionError('second approval')):
            panel.run_plan()
            self.finish(panel)
        report = json.loads(panel.result.read_text())
        self.assertEqual(report['status'], 'passed', report)
        saved = Plan.load(panel.result.parent / 'plan.json')
        self.assertEqual(saved.identity, panel.plan.identity)
        self.assertEqual(saved.phases[-1].provider, 'testflight')
        self.assertFalse(saved.phases[-1].approval_required)
        for provider in ('firebase', 'testflight'):
            self.assertTrue((self.root / (provider + '.json')).is_file())
        resumed = Executor().run(saved, panel.result.parent, resume=True)
        self.assertEqual(resumed['status'], 'passed')
        self.assertEqual([row['started_at'] for row in resumed['phases']],
                         [row['started_at'] for row in report['phases']])

    def test_failed_checks_block_start_authorized_effects(self):
        plan = start_authorized_effects(integrated(self.root, fail_gate=True))
        report = Executor().run(plan, self.root / 'failed')
        self.assertEqual(report['status'], 'failed')
        for provider in ('firebase', 'testflight'):
            self.assertFalse((self.root / (provider + '.json')).exists())

    def test_changed_package_blocks_start_authorized_uploads(self):
        plan = start_authorized_effects(integrated(self.root))
        executor = Executor()
        run_phase = executor.run_phase
        def tamper(phase, *args):
            row = run_phase(phase, *args)
            if phase.id == 'prepare':
                (self.root / 'package.bin').write_bytes(b'changed')
            return row
        with patch.object(executor, 'run_phase', side_effect=tamper):
            report = executor.run(plan, self.root / 'tampered')
        self.assertEqual(report['status'], 'failed')
        for provider in ('firebase', 'testflight'):
            self.assertFalse((self.root / (provider + '.json')).exists())

    def test_github_delivery_runs_after_tests_and_failed_tests_block_it(self):
        for fail in (False, True):
            root = self.root / str(fail)
            root.mkdir()
            plan = integrated(root, fail_gate=fail)
            github = Phase('github', (plan.phases[0].argv[0], '-c', 'pass'), str(root),
                           effect='publish', dependencies=('prepare',))
            journey = dict(plan.journey, destinations={**plan.journey['destinations'],
                'github': dict(identity='owner/repo/v1', steps=['github'])})
            plan = start_authorized_effects(replace(plan, journey=journey, phases=(*plan.phases, github)))
            self.assertFalse(plan.phases[-1].approval_required)
            self.assertEqual(plan.phases[-1].provider, 'github')
            report = Executor().run(plan, root / 'result')
            row = next(row for row in report['phases'] if row['id'] == 'github')
            self.assertEqual(row['status'], 'skipped' if fail else 'passed')

    def test_gui_start_authorizes_github_actions_with_an_overall_external_effect(self):
        for effect in ('dispatch', 'upload', 'publish'):
            project = OtherProject(self.root)
            project.make_plan = lambda *args, **kwargs: Plan('Fixture', 'GitHub', {}, (
                Phase('github', (project.interpreter, '-c', 'pass'), str(self.root), provider='github'),
                ), str(self.root / effect), effect=effect)
            panel = ManagerPanel(project)
            self.addCleanup(panel.close)
            panel.goal.setCurrentIndex(panel.goal.findData('advanced'))
            self.inspect(panel)
            self.assertFalse(panel.plan.phases[0].approval_required)
            with patch('build_manager.ui.QMessageBox.question', side_effect=AssertionError('extra approval')):
                panel.run_plan()
                self.finish(panel)
            self.assertEqual(json.loads(panel.result.read_text())['status'], 'passed')

    def test_unknown_upload_cannot_be_repeated_on_resume(self):
        plan = start_authorized_effects(integrated(self.root, fail_delivery=True))
        output = self.root / 'unknown'
        report = Executor().run(plan, output)
        self.assertEqual(next(row for row in report['phases'] if row['id'] == 'firebase')['status'], 'unknown')
        before = (self.root / 'firebase.json').read_bytes()
        resumed = Executor().run(plan, output, resume=True)
        self.assertEqual(resumed['status'], 'unknown')
        self.assertIn('reconciliation', resumed['error'])
        self.assertEqual((self.root / 'firebase.json').read_bytes(), before)

    def test_only_declared_tester_uploads_gain_start_authorization(self):
        plan = integrated(self.root)
        extra = tuple(Phase(name, plan.phases[0].argv, str(self.root), effect=effect, provider=provider)
                      for name, effect, provider in [('unknown-provider', 'upload', ''),
                          ('publish', 'publish', 'firebase'), ('dispatch', 'dispatch', 'testflight'),
                          ('unmapped', 'upload', '')])
        declared_phases = tuple(replace(phase, provider=phase.id) if phase.effect == 'upload' else phase for phase in plan.phases)
        updated = start_authorized_effects(replace(plan, journey={}, phases=(*declared_phases, *extra)))
        self.assertTrue(all(phase.approval_required for phase in updated.phases[-4:]))
        self.assertIn('Other external actions pause', start_scope(updated))
        for effect, provider in [('publish', 'firebase'), ('dispatch', 'testflight'), ('upload', '')]:
            with self.assertRaises(ValueError):
                replace(extra[0], effect=effect, provider=provider, approval_required=False)
        declared = replace(plan, journey={}, phases=(replace(plan.phases[-1], dependencies=(), provider='testflight'),))
        self.assertFalse(start_authorized_effects(declared).phases[0].approval_required)

    def test_declared_hosted_dispatch_uses_start_and_old_plans_keep_review(self):
        from test_run_choices import RunChoicesTests
        from build_manager.grouped_workflow import retained_proposal, group_workflow
        original = RunChoicesTests().hosted(self.root)
        plan = start_authorized_effects(original)
        self.assertEqual(plan.phases[0].provider, 'github')
        self.assertFalse(plan.phases[0].approval_required)
        self.assertEqual(Executor().run(plan, self.root / 'hosted')['status'], 'passed')
        original.save(self.root / 'old-hosted.json')
        self.assertTrue(Plan.load(self.root / 'old-hosted.json').phases[0].approval_required)
        old = integrated(self.root)
        proposal = retained_proposal(old)
        grouped = group_workflow(old, proposal=proposal)
        self.assertTrue(all(node.approval_required for node in grouped.phases if node.id.startswith('deliver.')))
        self.assertTrue(all('Start authorizes' not in node.description for node in proposal.phases))
