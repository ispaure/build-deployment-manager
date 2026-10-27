"""Real chained processes, retained artifact review and interrupted recovery."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace

from build_manager import Executor,Phase,Plan
from build_manager.workflows import approve,recover


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='workflow ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def phase(self,name,code,**kwargs):return Phase(name,(sys.executable,'-c',code),str(self.root),**kwargs)

    def test_prepare_review_resume_reuses_exact_artifact_and_effect_once(self):
        artifact=self.root/'prepared.txt';counter=self.root/'counter'
        prepare=self.phase('prepare',f'from pathlib import Path;Path({str(artifact)!r}).write_text("exact candidate")',artifacts=(str(artifact),))
        upload=self.phase('upload',f'from pathlib import Path;p=Path({str(counter)!r});p.write_text("accepted")',dependencies=('prepare',),effect='upload')
        plan=Plan('Fixture','workflow',{'commit':'fixed'},(prepare,upload),str(self.root/'workspace'))
        output=self.root/'result';first=Executor().run(plan,output)
        self.assertEqual(first['status'],'awaiting_review');self.assertFalse(counter.exists())
        permission=approve(plan,'upload',first)
        result=Executor().run(plan,output,resume=True,approvals=[permission])
        self.assertEqual(result['status'],'passed');self.assertEqual(counter.read_text(),'accepted')
        self.assertEqual(result['phases'][0]['started_at'],first['phases'][0]['started_at'])
        self.assertEqual(len(result['attempts']), 2)
        self.assertAlmostEqual(result['seconds'], first['seconds'] + result['attempt_seconds'])
        self.assertEqual(Executor().run(plan,output,resume=True)['status'],'passed')

    def test_recovery_never_repeats_uncertain_effect_and_artifact_loss_is_explicit(self):
        artifact=self.root/'a';artifact.write_text('fixed')
        import hashlib
        phase=self.phase('upload','pass',effect='upload')
        plan=Plan('Fixture','review',{},(phase,),str(self.root/'workspace'))
        report=dict(schema=1,plan_identity=plan.identity,phases=[dict(id='upload',status='running')])
        with self.assertRaisesRegex(ValueError,'reconciliation'):recover(plan,report)
        self.assertEqual(recover(plan,report,reconcile=lambda *_:dict(status='passed',operation_id=7))[0]['receipt']['operation_id'],7)
        report['phases']=[dict(id='upload',status='passed',artifacts=[dict(path=str(artifact),sha256=hashlib.sha256(b'fixed').hexdigest())])]
        artifact.unlink()
        with self.assertRaisesRegex(ValueError,'missing'):recover(plan,report)

    def test_offline_recipient_does_not_block_other_delivery_review_or_repeat_build(self):
        package = self.root / 'package'
        ready = self.root / 'connected'
        plan = Plan('Fixture', 'independent deliveries', {}, (
            self.phase('build', f'from pathlib import Path;Path({str(package)!r}).write_text("fixed")', artifacts=(str(package),)),
            self.phase('connect', f'from pathlib import Path;raise SystemExit(0 if Path({str(ready)!r}).exists() else 75)',
                       dependencies=('build',), effect='inspect', retry_exit_codes=(75,), retry_delay=.1),
            self.phase('offline-device', 'pass', effect='deploy', dependencies=('build', 'connect')),
            self.phase('other-delivery', 'pass', effect='upload', dependencies=('build',))), str(self.root / 'workspace'))
        output = self.root / 'result'
        first = Executor().run(plan, output)
        self.assertEqual(first['status'], 'awaiting_review')
        self.assertEqual(next(row for row in first['phases'] if row['id'] == 'connect')['status'], 'retrying')
        permission = approve(plan, 'other-delivery', first)
        ready.touch()
        second = Executor().run(plan, output, resume=True, approvals=[permission])
        self.assertEqual(second['status'], 'awaiting_review')
        self.assertEqual(next(row for row in second['phases'] if row['id'] == 'other-delivery')['status'], 'passed')
        permission = approve(plan, 'offline-device', second)
        final = Executor().run(plan, output, resume=True, approvals=[permission])
        self.assertEqual(final['status'], 'passed')
        self.assertEqual(final['phases'][0]['started_at'], first['phases'][0]['started_at'])

    def test_restart_retries_harmless_interrupted_step_but_keeps_dependency_failure(self):
        marker=self.root/'marker'
        a=self.phase('a','print("safe")')
        b=self.phase('b',f'from pathlib import Path;Path({str(marker)!r}).write_text("resumed")',dependencies=('a',))
        plan=Plan('Fixture','chain',{},(a,b),str(self.root/'workspace'))
        output=self.root/'result';first=Executor().run(plan,output)
        first['phases'][1]['status']='running';(output/'result.json').write_text(json.dumps(first))
        marker.unlink();result=Executor().run(plan,output,resume=True)
        self.assertEqual(result['status'],'passed');self.assertTrue(marker.exists())
        self.assertEqual(first['phases'][0]['started_at'],result['phases'][0]['started_at'])

    def test_changed_source_invalidates_review_and_unknown_schema_is_rejected(self):
        plan=Plan('Fixture','chain',{},(self.phase('a','pass'),),str(self.root/'workspace'))
        result=Executor().run(plan,self.root/'result')
        with self.assertRaises(ValueError):approve(replace(plan,source={'commit':'changed'}),'a',result)
        with self.assertRaises(ValueError):replace(plan,schema=99)

    def test_partial_provider_completion_preserves_success_and_reconciles_unknown(self):
        phases=(self.phase('prepare','print("fixed candidate")'),
                self.phase('provider-a','print("accepted")',dependencies=('prepare',),effect='upload'),
                self.phase('provider-b','raise SystemExit(3)',dependencies=('prepare',),effect='upload'))
        plan=Plan('Fixture','two destinations',{},phases,str(self.root/'workspace'))
        output=self.root/'result';first=Executor().run(plan,output)
        permissions=[approve(plan,name,first) for name in ('provider-a','provider-b')]
        partial=Executor().run(plan,output,resume=True,approvals=permissions)
        self.assertEqual(partial['status'],'unknown')
        self.assertEqual([row['status'] for row in partial['phases']],['passed','passed','unknown'])
        result=Executor().run(plan,output,resume=True,reconcile=lambda name,row:dict(status='passed',operation_id='verified-existing'))
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['phases'][1]['started_at'],partial['phases'][1]['started_at'])

    def test_effect_intent_and_operation_id_are_durable_before_child_starts(self):
        output=self.root/'result'
        code=f'import json;from pathlib import Path;r=json.loads(Path({str(output/"result.json")!r}).read_text());s=[p for p in r["phases"] if p["id"]=="effect"][0];assert s["status"]=="running" and s["operation_id"]'
        plan=Plan('Fixture','durable intent',{},(self.phase('prepare','pass'),
             self.phase('effect',code,dependencies=('prepare',),effect='upload')),str(self.root/'workspace'))
        first=Executor().run(plan,output)
        result=Executor().run(plan,output,resume=True,approvals=[approve(plan,'effect',first)])
        self.assertEqual(result['status'],'passed')

    def test_invalid_serialized_commands_and_future_schema_fail_without_execution(self):
        for data in ([],{},dict(phases=[dict(argv='shell command')])):
            with self.assertRaises(ValueError):Plan.from_data(data)

    @unittest.skipIf(sys.platform=='win32','POSIX signal grace; Windows uses owned job termination')
    def test_declared_grace_allows_owned_helper_cleanup_before_escalation(self):
        from threading import Event,Timer
        from dataclasses import replace
        marker=self.root/'retired';cancelled=Event();timer=Timer(.05,cancelled.set)
        code=f'import signal,time;from pathlib import Path\ndef stop(*_):\n time.sleep(1.2);Path({str(marker)!r}).write_text("cleaned");raise SystemExit(0)\nsignal.signal(signal.SIGTERM,stop);print("ready",flush=True);time.sleep(30)'
        def event(value):
            if value.get('type')=='output' and value.get('text','').startswith('ready'):timer.start()
        phase=replace(self.phase('helper',code),stop_grace=3)
        plan=Plan('Fixture','grace',{},(phase,),str(self.root/'workspace'))
        try:result=Executor(cancelled=cancelled,event=event).run(plan,self.root/'result')
        finally:timer.cancel()
        self.assertEqual(result['status'],'cancelled');self.assertEqual(marker.read_text(),'cleaned')

    def test_remote_controller_cleanup_grace_round_trips_and_stays_bounded(self):
        phase = replace(self.phase('controller', 'pass'), stop_grace=240)
        plan = Plan('Fixture','remote cleanup',{},(phase,),str(self.root/'workspace'))
        self.assertEqual(Plan.from_data(plan.data()).phases[0].stop_grace,240)
        legacy = plan.data()
        legacy['phases'][0].pop('stop_grace')
        self.assertEqual(Plan.from_data(legacy).phases[0].stop_grace,1)
        for invalid in (0,301,float('inf'),float('nan')):
            with self.subTest(grace=invalid), self.assertRaises(ValueError):
                replace(phase,stop_grace=invalid)
