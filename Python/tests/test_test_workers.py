"""Real cross-process admission for nested test pools and idle configuration."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from build_manager import Executor, Phase, Plan
from build_manager.resources import HostResourceSlots
from build_manager import test_workers as workers


class WorkerBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.resources = self.root / 'resources'
        workers.configure(dict(per_platform=4, host=8), self.resources)

    def plan(self, name, platform='macos'):
        marker = self.root / (name + '.json')
        code = ('import json,os,subprocess,sys,time;from pathlib import Path;'
                f'n=int(os.environ[{workers.ENV_RESERVED!r}]);start=time.monotonic();'
                'children=[subprocess.Popen([sys.executable,"-c","import time;time.sleep(.3)"]) for _ in range(n)];'
                'assert all(p.wait()==0 for p in children);'
                f'Path({str(marker)!r}).write_text(json.dumps([start,time.monotonic(),n]))')
        plan = Plan(name, 'Test', {}, (Phase('tests', (sys.executable, '-c', code), str(self.root)),),
                    str(self.root / (name + '-workspace')))
        return workers.reserve(plan, platform, ['tests'], accelerated=['tests'], directory=self.resources)

    def launch(self, plans):
        processes = []
        for index, plan in enumerate(plans):
            path = self.root / f'plan-{index}.json'
            plan.save(path)
            code = ('import sys;from build_manager import Executor,Plan;'
                    'r=Executor(resource_directory=sys.argv[3]).run(Plan.load(sys.argv[1]),sys.argv[2]);'
                    'assert r["status"]=="passed",r')
            processes.append(subprocess.Popen([sys.executable, '-c', code, str(path),
                str(self.root / f'result-{index}'), str(self.resources)], stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        try:
            for process in processes:
                out, error = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, (out + error).decode())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_separate_managers_share_host_budget_and_per_platform_ceiling(self):
        plans = [self.plan('a'), self.plan('b'), self.plan('c', 'ios')]
        self.launch(plans)
        rows = [json.loads((self.root / f'{name}.json').read_text()) for name in 'abc']
        a, b, c = rows
        self.assertTrue(a[1] <= b[0] or b[1] <= a[0], rows)
        self.assertTrue(any(max(row[0], c[0]) < min(row[1], c[1]) for row in (a, b)), rows)
        events = sorted((stamp, change) for start, end, count in rows for stamp, change in ((start, count), (end, -count)))
        active = peak = 0
        for _, change in events:
            active += change
            peak = max(peak, active)
        self.assertEqual(peak, 8)
        self.assertEqual(active, 0)

    def test_three_platforms_cannot_multiply_the_host_budget(self):
        self.launch([self.plan(name, platform) for name, platform in zip('abc', ('macos', 'ios', 'android'))])
        rows = [json.loads((self.root / f'{name}.json').read_text()) for name in 'abc']
        events = sorted((stamp, change) for start, end, count in rows for stamp, change in ((start, count), (end, -count)))
        active = peak = 0
        for _, change in events:
            active += change
            peak = max(peak, active)
        self.assertEqual(peak, 8)

    def test_settings_change_requires_idle_and_old_plans_fail_before_launch(self):
        plan = self.plan('old')
        phase = plan.phases[0]
        with HostResourceSlots(self.resources).acquire(phase.resources, plan.capacities, cancelled=Event(), timeout=1):
            workers.configure(dict(per_platform=4, host=8), self.resources)
            with self.assertRaisesRegex(ValueError, 'active'):
                workers.configure(dict(per_platform=2, host=4), self.resources)
            self.assertEqual(workers.limits(self.resources), dict(per_platform=4, host=8))
        workers.configure(dict(per_platform=2, host=4), self.resources)
        result = Executor(resource_directory=self.resources).run(plan, self.root / 'stale')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['phases'][0]['launch_state'], 'not_started')
        self.assertFalse((self.root / 'old.json').exists())
        replacement = self.plan('new')
        result = Executor(resource_directory=self.resources).run(replacement, self.root / 'fresh')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(json.loads((self.root / 'new.json').read_text())[2], 2)

    def test_legacy_phases_without_resources_do_not_open_the_resource_directory(self):
        unusable = self.root / 'not-a-directory'
        unusable.write_text('preserve')
        plan = Plan('Legacy', 'Test', {}, (Phase('plain', (sys.executable, '-c', 'pass'), str(self.root)),),
                    str(self.root / 'legacy-workspace'))
        self.assertEqual(Executor(resource_directory=unusable).run(plan, self.root / 'legacy')['status'], 'passed')
        self.assertEqual(unusable.read_text(), 'preserve')

    def test_wait_cancellation_releases_partial_reservations(self):
        plan = self.plan('cancelled')
        phase = plan.phases[0]
        cancelled = Event()
        with HostResourceSlots(self.resources).acquire(phase.resources, plan.capacities, cancelled=Event(), timeout=1):
            result = Executor(resource_directory=self.resources, cancelled=cancelled,
                event=lambda event: cancelled.set() if event.get('type') == 'waiting' else None).run(plan, self.root / 'result')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['phases'][0]['launch_state'], 'not_started')
        with HostResourceSlots(self.resources).acquire({workers.HOST: 8}, plan.capacities, cancelled=Event(), timeout=0):
            pass

    def test_defaults_bounds_and_unreserved_or_oversized_requests(self):
        with patch.object(workers.os, 'cpu_count', return_value=16):
            self.assertEqual(workers.limits(self.root / 'empty'), dict(per_platform=4, host=8))
        for values in (dict(per_platform=9, host=16), dict(per_platform=True, host=8), dict(per_platform=4, host=2)):
            with self.assertRaises(ValueError):
                workers.configure(values, self.resources)
        plan = self.plan('unreserved')
        with self.assertRaises(ValueError):
            workers.admitted_environment(replace(plan.phases[0], resources={}), plan, self.resources)
        with self.assertRaises(ValueError):
            workers.admitted_environment(replace(plan.phases[0], environment={workers.ENV_WORKERS: '4'}), plan, self.resources)
        legacy = replace(plan.phases[0], resources={}, environment={})
        self.assertEqual(workers.admitted_environment(legacy, plan, self.resources), {})


if __name__ == '__main__':
    unittest.main()
