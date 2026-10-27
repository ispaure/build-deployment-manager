"""Retained checks preserve failed siblings and reject incomplete old evidence."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from build_manager.models import Phase, Plan
from build_manager.retained_checks import verify_checks


class RetainedChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root/'original.xml'
        self.original.write_text('<testsuite/>')
        self.retained = self.root/'retained.xml'
        self.retained.write_bytes(self.original.read_bytes())
        self.plan = Plan('fixture', 'test', {'commit': 'a'*40}, (
            Phase('setup', ('python', 'setup.py'), str(self.root), effect='test', kind='setup'),
            Phase('native', ('python', 'native.py'), str(self.root), dependencies=('setup',),
                  artifacts=(str(self.original),), effect='test'),
            Phase('failed', ('python', 'broken.py'), str(self.root), effect='test'),
            Phase('upload', ('python', 'upload.py'), str(self.root), effect='upload'),
        ), str(self.root/'workspace'))
        self.report = dict(schema=1, status='unknown', plan_identity=self.plan.identity,
                           source=self.plan.source, engine={'manager': {'commit': 'b'*40}}, phases=[
            dict(id='setup', status='passed', log='setup.log'),
            dict(id='native', status='passed', log='native.log', artifacts=[dict(
                path=str(self.retained), original_path=str(self.original),
                sha256=hashlib.sha256(self.original.read_bytes()).hexdigest())]),
            dict(id='failed', status='failed', log='failed.log'),
            dict(id='upload', status='passed', log='upload.log'),
        ])
        for row in self.report['phases']:
            (self.root/row['log']).write_text(row['status'])
        self.save()

    def save(self):
        self.plan.save(self.root/'plan.json')
        (self.root/'result.json').write_text(json.dumps(self.report))

    def verify(self, steps=('native',), **kwargs):
        return verify_checks(self.root, self.plan.identity, steps, **kwargs)

    def test_passed_branch_keeps_failed_sibling_and_unknown_aggregate_unchanged(self):
        before = (self.root/'result.json').read_bytes()
        receipt = self.verify()
        self.assertEqual([row['id'] for row in receipt['checks']], ['setup', 'native'])
        self.assertFalse(receipt['fresh_execution'])
        self.assertFalse(receipt['authorizes_source_reuse'])
        self.assertEqual(before, (self.root/'result.json').read_bytes())
        self.assertEqual(self.verify(expect_review=receipt['identity']), receipt)

    def test_missing_failed_and_unknown_prerequisites_rejected(self):
        for status in ('failed', 'unknown', 'skipped', 'running'):
            with self.subTest(status=status):
                self.report['phases'][0]['status'] = status
                self.save()
                with self.assertRaisesRegex(ValueError, 'did not pass'):
                    self.verify()
        self.report['phases'].pop(0)
        self.save()
        with self.assertRaisesRegex(ValueError, 'did not pass'):
            self.verify()

    def test_external_effect_and_failed_check_never_imported(self):
        for step in ('upload', 'failed'):
            with self.subTest(step=step), self.assertRaises(ValueError):
                self.verify((step,))

    def test_log_and_report_changes_invalidate_review_binding(self):
        identity = self.verify()['identity']
        (self.root/'native.log').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            self.verify(expect_review=identity)
        identity = self.verify()['identity']
        self.report['phases'][2]['diagnostic'] = 'new sibling diagnosis'
        self.save()
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            self.verify(expect_review=identity)

    def test_missing_original_retained_or_inventory_never_accepted(self):
        for path in (self.original, self.retained):
            data = path.read_bytes()
            path.unlink()
            with self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(data)
        self.report['phases'][1]['artifacts'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.verify()

    def test_different_source_plan_and_linked_log_rejected(self):
        self.report['source'] = {'commit': 'c'*40}
        self.save()
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.verify()
        self.report['source'] = self.plan.source
        self.save()
        path = self.root/'native.log'
        path.unlink()
        path.symlink_to(self.root/'setup.log')
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.verify()
        path.unlink()
        path.write_text('passed')
        self.plan = replace(self.plan, operation='different')
        self.plan.save(self.root/'plan.json')
        with self.assertRaises(ValueError):
            self.verify()
