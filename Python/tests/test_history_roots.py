"""Saved runs remain independently addressable across a results-root change."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Phase, Plan
from build_manager.api import ManagerAPI, review_run, run_plan
from build_manager.history import load_run
from build_manager.registry import read_project_descriptor
from build_manager.retention import has_retention_protection, set_workflow_hold
from build_manager.test_storage import result_roots


class HistoryRootsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.primary = self.project / 'tmp/test-results/manager'
        self.legacy = self.project / 'test-results/manager'
        self.evidence = self.project / 'loose-evidence'
        self.descriptor = dict(schema=1, adapter_api=1, project_id='fixture', name='Fixture',
            interpreter='python', bridge='bridge.py', results='test-results/manager',
            capabilities=dict(platforms=['native'], operations=['Check']),
            adapter_actions=['storage_maintenance'])
        self.file = self.project / 'build-project.json'
        self.write_descriptor()
        self.api = ManagerAPI(self.root / 'registry')
        self.key = self.api.registry.add(self.project)
        self.old_digest = read_project_descriptor(self.project)[1]

    def write_descriptor(self, **changes):
        self.file.write_text(json.dumps(dict(self.descriptor, **changes)))

    def cutover(self):
        self.write_descriptor(results='tmp/test-results/manager',
                              legacy_results=['test-results/manager'], test_evidence=['loose-evidence'])

    def saved_run(self, root, name):
        output = root / name
        workspace = self.project / ('workspace-old' if root == self.legacy else 'workspace-new')
        workspace.mkdir(exist_ok=True)
        artifact = workspace / 'evidence.txt'
        script = 'from pathlib import Path; Path(' + repr(str(artifact)) + ').write_text("fixture")'
        plan = Plan('Fixture', 'Check', {},
            (Phase('check', (sys.executable, '-B', '-c', script), str(self.project),
                   artifacts=(str(artifact),)),),
            str(workspace), adapter=dict(checkout=str(self.project), project_id='fixture', api=1,
                                        descriptor_sha256=self.old_digest))
        report = run_plan(plan, output)
        self.assertEqual(report['status'], 'passed')
        return output, plan

    def test_history_merges_declared_roots_in_global_order_and_keeps_exact_paths(self):
        old, _ = self.saved_run(self.legacy, 'same')
        self.assertEqual([row['path'] for row in self.api.history(self.key)['runs']],
                         [str(old / 'result.json')])
        new, _ = self.saved_run(self.primary, 'same')
        self.saved_run(self.evidence, 'unrelated')
        self.cutover()
        os.utime(old / 'result.json', (100, 100))
        os.utime(new / 'result.json', (200, 200))
        self.assertEqual(self.api.history(self.key, limit=1)['runs'][0]['path'], str(new / 'result.json'))
        history = self.api.history(self.key)
        self.assertEqual(history['directory'], str(self.primary))
        self.assertEqual([row['path'] for row in history['runs']],
                         [str(new / 'result.json'), str(old / 'result.json')])
        self.assertEqual(result_roots(self.api._project(self.key)),
                         {self.primary: False, self.legacy: False, self.evidence: True})

    def test_legacy_review_resume_and_retirement_preserve_exact_identity_and_holds(self):
        old, plan = self.saved_run(self.legacy, 'same')
        new, _ = self.saved_run(self.primary, 'same')
        self.cutover()
        changed_digest = read_project_descriptor(self.project)[1]
        self.assertNotEqual(changed_digest, self.old_digest)
        self.assertEqual(review_run(old)['identity'], plan.identity)
        _, saved = load_run(old / 'result.json')
        artifact = Path(saved['phases'][0]['artifacts'][0]['path'])
        self.assertTrue(artifact.is_relative_to(old))
        artifact_hash = sha256(artifact.read_bytes()).hexdigest()
        report = run_plan(old / 'plan.json', old, resume=True, maintenance=self.api.storage_maintenance)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['storage_maintenance']['status'], 'failed')
        self.assertIn('current adapter differs', report['storage_maintenance']['error'])
        self.api.registry.trust(self.key, expected_digest=changed_digest)
        with self.assertRaisesRegex(ValueError, 'current adapter differs'):
            self.api.storage_maintenance(plan)
        self.assertEqual(load_run(old / 'result.json')[0].identity, plan.identity)
        old_plan = sha256((old / 'plan.json').read_bytes()).hexdigest()
        new_report = (new / 'result.json').read_bytes()
        workspace = Path(plan.workspace)
        _, old_report = load_run(old / 'result.json')
        old_report['holds'] = [str(workspace), str(old)]
        (old / 'result.json').write_text(json.dumps(old_report))
        for path in (workspace, old):
            set_workflow_hold(path, str(old))
        set_workflow_hold(workspace, str(new))
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.api.retire_run('same', project=self.key, confirmed=True)
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.api.retire_run(str(old / 'result.json'), project=self.key)
        retirement = self.api.retire_run(str(old / 'result.json'), project=self.key, confirmed=True)
        self.assertEqual(retirement['released_holds'], 2)
        self.assertEqual(sha256((old / 'plan.json').read_bytes()).hexdigest(), old_plan)
        self.assertEqual((new / 'result.json').read_bytes(), new_report)
        self.assertEqual(sha256(artifact.read_bytes()).hexdigest(), artifact_hash)
        self.assertFalse(has_retention_protection(old))
        self.assertTrue(has_retention_protection(workspace))
        with self.assertRaisesRegex(ValueError, 'retired'):
            run_plan(old / 'plan.json', old, resume=True)

    def test_linked_and_undeclared_runs_are_outside_project_retirement(self):
        self.cutover()
        external = self.root / 'external'
        output, _ = self.saved_run(external, 'outside')
        self.legacy.parent.mkdir(parents=True)
        self.legacy.symlink_to(external, target_is_directory=True)
        self.assertEqual(self.api.history(self.key)['runs'], [])
        for path in (output, self.legacy / output.name):
            with self.assertRaisesRegex(ValueError, 'exact saved run path'):
                self.api.retire_run(str(path), project=self.key, confirmed=True)

    def test_legacy_declarations_reject_escape_and_wrong_shape(self):
        for value in ('test-results', ['../outside'], ['/outside'], ['C:/outside'], ['.']):
            with self.subTest(value=value):
                self.write_descriptor(legacy_results=value)
                with self.assertRaisesRegex(ValueError, 'checkout-relative'):
                    read_project_descriptor(self.project)
