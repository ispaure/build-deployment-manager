"""Read-only project result discovery and identity checks."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Phase, Plan
from build_manager.history import recent_runs, load_run, read_report


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, name='run'):
        folder = self.root / name
        folder.mkdir()
        plan = Plan('Fixture', 'Test', {}, (Phase('test', (sys.executable, '-c', 'pass'), str(self.root)),),
                    str(self.root / 'workspace'))
        plan.save(folder / 'plan.json')
        report = dict(schema=1, plan_identity=plan.identity, status='passed', seconds=.2,
                      operation='Test', phases=[dict(id='test', status='passed', seconds=.1)])
        path = folder / 'result.json'
        path.write_text(json.dumps(report))
        return path

    def test_history_is_one_level_limited_and_handles_corruption(self):
        self.fixture('one')
        broken = self.fixture('broken')
        broken.write_text('{broken')
        nested = self.root / 'build' / 'cache'
        nested.mkdir(parents=True)
        (nested / 'result.json').write_text('{}')
        rows = recent_runs(self.root)
        self.assertEqual(len(rows), 2)
        self.assertIn('unreadable', [row['status'] for row in rows])
        self.assertEqual(len(recent_runs(self.root, 1)), 1)
        self.assertEqual(recent_runs(self.root / 'missing'), [])

    def test_load_checks_plan_identity_without_executing(self):
        path = self.fixture()
        plan, report = load_run(path)
        self.assertEqual(plan.identity, report['plan_identity'])
        report['plan_identity'] = 'changed'
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'identity'):
            load_run(path)

    def test_bad_case_or_timing_is_rejected_before_ui(self):
        path = self.fixture()
        report = json.loads(path.read_text())
        report['phases'][0]['tests'] = [None]
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'case'):
            read_report(path)
        report['phases'][0].pop('tests')
        report['seconds'] = float('nan')
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'duration'):
            read_report(path)

    def test_bad_recovery_evidence_is_rejected_before_ui(self):
        path = self.fixture()
        report = json.loads(path.read_text())
        for value in (None, [], dict(environment='android', target='owned', status='recovered',
                                    attempts=[{}], checks=[])):
            report['phases'][0]['recovery'] = value
            path.write_text(json.dumps(report))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'recovery'):
                read_report(path)
