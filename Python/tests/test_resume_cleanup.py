"""Resume invalidates attempt-bound cleanup guards without replaying external effects."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Executor, Phase, Plan


class ResumeCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='resume-cleanup-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def phase(self, name, code, **options):
        return Phase(name, (sys.executable, '-c', code), str(self.root), **options)

    def test_failed_build_resume_repeats_cleanup_and_serializes_all_three_owners(self):
        from copy import deepcopy
        from unittest.mock import patch
        from build_manager.api import run_plan, review_run
        repaired, active, events, runtime, provider = (self.root / name for name in ('repaired', 'active', 'events', 'runtime', 'provider'))
        host_ids = tuple(f'host-proof-{index}' for index in range(9))
        phases = [self.phase(name, 'pass') for name in host_ids]
        phases.append(self.phase('build', f'from pathlib import Path;raise SystemExit(0 if Path({str(repaired)!r}).exists() else 1)',
                                 dependencies=host_ids, effect='build'))
        for index in range(3):
            previous = self.root / f'clean-{index - 1}'
            owner = f'owner-{index}'
            code = f'''from pathlib import Path
active=Path({str(active)!r})
assert {index} == 0 or Path({str(previous)!r}).exists(), 'Previous owner cleanup has not completed'
with active.open('x') as stream: stream.write({owner!r})
with Path({str(events)!r}).open('a') as stream: stream.write({(owner + chr(10))!r})
'''
            phases.append(self.phase(owner, code, dependencies=('build',) + ((f'cleanup-{index - 1}',) if index else ())))
            code = f'''from pathlib import Path
active=Path({str(active)!r})
if active.exists() and active.read_text() == {owner!r}:
    active.unlink()
    Path({str(self.root / f'clean-{index}')!r}).touch()
    with Path({str(events)!r}).open('a') as stream: stream.write({('cleanup-' + str(index) + chr(10))!r})
'''
            phases.append(self.phase(f'cleanup-{index}', code, dependencies=(owner,), always=True))
        phases.extend((self.phase('runtime-tools', 'pass', dependencies=host_ids),
            self.phase('runtime', f'from pathlib import Path;assert not Path({str(repaired)!r}).exists() or Path({str(self.root/"clean-2")!r}).exists();'
                       f'p=Path({str(runtime)!r});p.write_text(p.read_text()+"once" if p.exists() else "once")',
                       dependencies=('runtime-tools', 'cleanup-2')),
            self.phase('runtime-cleanup', 'pass', dependencies=('runtime',), always=True),
            self.phase('provider', f'from pathlib import Path;p=Path({str(provider)!r});p.write_text(p.read_text()+"once" if p.exists() else "once")',
                       dependencies=('runtime-tools',), effect='deploy', approval_required=False)))
        plan = Plan('Fixture', 'serial owned tests', {}, tuple(phases), str(self.root/'workspace'), max_workers=3)
        output = self.root/'result'
        first = run_plan(plan, output, confirmed=True, expected_identity=plan.identity)
        before = {row['id']: row for row in first['phases']}
        self.assertEqual(first['status'], 'failed')
        self.assertEqual(before['build']['status'], 'failed')
        for index in range(3):
            self.assertEqual(before[f'owner-{index}']['status'], 'skipped')
            self.assertEqual(before[f'cleanup-{index}']['status'], 'passed')
        self.assertEqual(before['runtime']['status'], 'passed')
        self.assertFalse(events.exists())
        self.assertEqual(runtime.read_text(), 'once')
        original_plan = (output/'plan.json').read_bytes()
        original_report = (output/'result.json').read_bytes()
        repaired.touch()
        changed_engine = deepcopy(first['engine'])
        changed_engine['manager']['commit'] = 'f' * 40
        with patch('build_manager.identity.capture_engine_source_identity', return_value=changed_engine):
            with self.assertRaisesRegex(ValueError, 'engine review identity'):
                run_plan(plan, output, confirmed=True, expected_identity=plan.identity, resume=True)
            self.assertEqual((output/'result.json').read_bytes(), original_report)
            self.assertFalse(events.exists())
            review = review_run(output)
            self.assertEqual(review['identity'], plan.identity)
            second = run_plan(plan, output, confirmed=True, expected_identity=plan.identity, resume=True,
                              engine_review=review['engine_change']['identity'])
        after = {row['id']: row for row in second['phases']}
        self.assertEqual(second['status'], 'passed', second)
        self.assertEqual((output/'plan.json').read_bytes(), original_plan)
        self.assertEqual(events.read_text().splitlines(), [name for i in range(3) for name in (f'owner-{i}', f'cleanup-{i}')])
        self.assertFalse(active.exists())
        for name in (*host_ids, 'runtime-tools', 'provider'):
            self.assertEqual(after[name], before[name])
        for name in ('cleanup-0', 'cleanup-1', 'cleanup-2', 'runtime', 'runtime-cleanup'):
            self.assertNotEqual(after[name]['operation_id'], before[name]['operation_id'])
        self.assertEqual(runtime.read_text(), 'onceonce')
        self.assertEqual(provider.read_text(), 'once')
        self.assertEqual(second['engine'], changed_engine)
        self.assertEqual(set(second['engine_history'][-1]['retained_phases']), {*host_ids, 'runtime-tools', 'provider'})

    def test_completed_nonexternal_consumer_refreshes_but_external_outcomes_are_retained(self):
        repaired, inspected, delivered, uncertain = (self.root/name for name in ('repaired', 'inspected', 'delivered', 'uncertain'))
        plan = Plan('Fixture', 'retained effects', {}, (
            self.phase('build', f'from pathlib import Path;raise SystemExit(0 if Path({str(repaired)!r}).exists() else 1)', effect='build'),
            self.phase('inspect', f'from pathlib import Path;Path({str(inspected)!r}).write_text("ready" if Path({str(repaired)!r}).exists() else "unavailable")',
                       waits_for=('build',), effect='inspect'),
            self.phase('delivered', f'from pathlib import Path;p=Path({str(delivered)!r});p.write_text(p.read_text()+"once" if p.exists() else "once")',
                       dependencies=('inspect',), effect='deploy', approval_required=False),
            self.phase('uncertain', f'from pathlib import Path;p=Path({str(uncertain)!r});p.write_text(p.read_text()+"once" if p.exists() else "once");raise SystemExit(1)',
                       effect='deploy', approval_required=False),
            self.phase('cleanup', 'pass', always=True),
        ), str(self.root/'workspace'), max_workers=3)
        output = self.root/'result'
        first = Executor().run(plan, output)
        before = {row['id']: row for row in first['phases']}
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(before['delivered']['status'], 'passed')
        self.assertEqual(before['uncertain']['status'], 'unknown')
        self.assertEqual(inspected.read_text(), 'unavailable')
        repaired.touch()
        second = Executor().run(plan, output, resume=True)
        after = {row['id']: row for row in second['phases']}
        self.assertEqual(second['status'], 'unknown')
        self.assertEqual(inspected.read_text(), 'ready')
        self.assertNotEqual(before['inspect']['operation_id'], after['inspect']['operation_id'])
        self.assertNotEqual(before['cleanup']['operation_id'], after['cleanup']['operation_id'])
        for name in ('delivered', 'uncertain'):
            self.assertEqual(after[name], before[name])
        self.assertEqual(delivered.read_text(), 'once')
        self.assertEqual(uncertain.read_text(), 'once')
