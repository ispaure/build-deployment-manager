"""Real process overlap and cross-process host resource exclusion."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event,Timer
import unittest

from build_manager import Executor,Phase,Plan


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='scheduler ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def phase(self,name,*,dependencies=(),resources=None,code=None,always=False):
        target=self.root/(name+'.json')
        body=code or f'import time,json;from pathlib import Path;a=time.time();time.sleep(.3);Path({str(target)!r}).write_text(json.dumps([a,time.time()]))'
        return Phase(name,(sys.executable,'-c',body),str(self.root),dependencies=dependencies,resources=resources or {},always=always)

    def run_plan(self,phases,workers=2):
        plan=Plan('Fixture','parallel',{},tuple(phases),str(self.root/'workspace'),max_workers=workers)
        return Executor(resource_directory=self.root/'resources').run(plan,self.root/'result')

    def times(self,name):return json.loads((self.root/(name+'.json')).read_text())

    def test_independent_branches_overlap_and_dependency_waits(self):
        result=self.run_plan([self.phase('a'),self.phase('b'),self.phase('c',dependencies=('a','b'))])
        self.assertEqual(result['status'],'passed')
        a,b,c=[self.times(name) for name in 'abc']
        self.assertLess(max(a[0],b[0]),min(a[1],b[1]));self.assertGreaterEqual(c[0],max(a[1],b[1]))

    def test_exclusive_resources_prevent_overlap_without_deadlock(self):
        result=self.run_plan([self.phase('a',resources={'device:fixture':1,'workspace:fixture':1}),
                              self.phase('b',resources={'workspace:fixture':1,'device:fixture':1})])
        self.assertEqual(result['status'],'passed')
        a,b=self.times('a'),self.times('b')
        self.assertTrue(a[1]<=b[0] or b[1]<=a[0])

    def test_failure_blocks_consumer_and_cleanup_runs_once(self):
        result=self.run_plan([self.phase('fail',code='raise SystemExit(3)'),self.phase('independent'),
            self.phase('dependent',dependencies=('fail',)),self.phase('cleanup',code='print("owned cleanup")',always=True)])
        self.assertEqual([row['status'] for row in result['phases']],['failed','passed','skipped','passed'])

    def test_two_manager_processes_share_hostwide_device_lock(self):
        processes=[]
        for name in ('a','b'):
            phase=self.phase(name,resources={'device:cross-process-fixture':1})
            plan=Plan(name,'check',{},(phase,),str(self.root/(name+'-workspace')))
            path=self.root/(name+'-plan.json');plan.save(path)
            code='from build_manager import Executor,Plan;from pathlib import Path;import sys;r=Executor(resource_directory=sys.argv[3]).run(Plan.load(sys.argv[1]),sys.argv[2]);raise SystemExit(r["status"]!="passed")'
            processes.append(subprocess.Popen([sys.executable,'-c',code,str(path),str(self.root/(name+'-result')),str(self.root/'resources')],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        for process in processes:
            stdout,stderr=process.communicate(timeout=15);self.assertEqual(process.returncode,0,stderr.decode())
        a,b=self.times('a'),self.times('b');self.assertTrue(a[1]<=b[0] or b[1]<=a[0])

    def test_parallel_cancellation_retires_descendants_then_owned_cleanup(self):
        cancelled=Event();started=set();timer=Timer(.1,cancelled.set)
        def event(value):
            if value.get('status')=='running':
                started.add(value['id'])
                if started=={'a','b'}:timer.start()
        code='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);time.sleep(30)'
        phases=(self.phase('a',code=code),self.phase('b',code=code),self.phase('cleanup',always=True,code='print("only owned cleanup")'))
        plan=Plan('Fixture','cancel',{},phases,str(self.root/'workspace'),max_workers=2)
        try:
            result=Executor(cancelled=cancelled,event=event,resource_directory=self.root/'resources').run(plan,self.root/'result')
        finally:timer.cancel()
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual([row['status'] for row in result['phases']],['cancelled','cancelled','passed'])
        self.assertLess(result['seconds'],5)

    def test_simultaneous_build_allocations_use_one_project_counter(self):
        path=self.root/'numbers.json'
        code='from build_manager.versions import reserve_number;import sys;print(reserve_number(sys.argv[1],maximum=100))'
        processes=[subprocess.Popen([sys.executable,'-c',code,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
        values=[]
        for process in processes:
            stdout,stderr=process.communicate(timeout=15);self.assertEqual(process.returncode,0,stderr.decode());values.append(int(stdout))
        self.assertEqual(sorted(values),[1,2,3,4])

    def test_branch_cleanup_can_unblock_next_sequential_device(self):
        phases=(self.phase('first'),self.phase('first-cleanup',dependencies=('first',),always=True,code='print("retired first device")'),
                self.phase('next',dependencies=('first-cleanup',)))
        result=self.run_plan(phases)
        self.assertEqual(result['status'],'passed')
        self.assertEqual([row['id'] for row in result['phases']],['first','first-cleanup','next'])
