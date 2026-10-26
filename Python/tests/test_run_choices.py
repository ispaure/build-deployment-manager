"""Per-platform execution, explicit remote effects and one-run inputs."""
import json,os,sys,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PySide6.QtWidgets import QApplication,QPushButton,QScrollArea
from build_manager import Executor,Phase,Plan
from build_manager.journeys import request,validate_plan
from build_manager.workflows import approve,recover
from build_manager.registry import Registry
from build_manager.app import ManagerWindow
from build_manager.ui import ManagerPanel
from build_manager.run_fields import validate_fields,validate_overrides
from test_journeys import CAPABILITY
from test_ui import OtherProject


class RunChoicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def hosted(self,root,code='pass'):
        return Plan('Fixture','Hosted checks',{'commit':'exact'},(
            Phase('launch-checks',(sys.executable,'-c',code),str(root),effect='dispatch'),
            Phase('verified',(sys.executable,'-c','pass'),str(root),dependencies=('launch-checks',),effect='test')),
            str(root/'workspace'),journey=dict(schema=1,goal='validate',platforms={'ios':['verified']},destinations={},
                executions={'ios':dict(backend='GitHub',steps=['launch-checks'])}))

    def test_remote_validation_is_a_reviewed_dispatch_not_publication(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);marker=root/'executed'
            plan=self.hosted(root,f'from pathlib import Path;Path({str(marker)!r}).touch()')
            validate_plan(plan,dict(goal='validate',platforms=['ios'],destinations=[],backends={'ios':'GitHub'}))
            first=Executor().run(plan,root/'result')
            self.assertEqual(first['status'],'awaiting_review');self.assertFalse(marker.exists())
            final=Executor().run(plan,root/'result',resume=True,approvals=[approve(plan,'launch-checks',first)])
            self.assertEqual(final['status'],'passed');self.assertTrue(marker.exists())
            self.assertFalse(any(phase.effect in {'publish','upload','deploy'} for phase in plan.phases))

    def test_unknown_dispatch_requires_reconciliation_and_unassigned_dispatch_is_rejected(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);plan=self.hosted(root,'raise SystemExit(3)')
            first=Executor().run(plan,root/'result')
            final=Executor().run(plan,root/'result',resume=True,approvals=[approve(plan,'launch-checks',first)])
            self.assertEqual(final['status'],'unknown')
            with self.assertRaisesRegex(ValueError,'reconciliation'):recover(plan,final)
            data=plan.data();data['journey']['executions']={}
            with self.assertRaisesRegex(ValueError,'declared platform'):Plan.from_data(data)

    def test_platform_choice_is_preserved_and_changes_invalidate_review(self):
        with TemporaryDirectory() as directory:
            project=OtherProject(Path(directory));project.journey_capability=deepcopy(CAPABILITY)
            project.journey_capability['selectable_backends']=True
            for row in project.journey_capability['platforms'].values():row['backend']='Local fixture'
            project.backend_options=lambda *_:('Local fixture','GitHub')
            panel=ManagerPanel(project);panel.show()
            try:
                panel.platform_checks['ios'].setChecked(True)
                panel.platform_backends['ios'].setCurrentText('GitHub')
                self.assertEqual(panel.revision.text(),'working-tree')
                self.assertIn('Choose Latest commit', panel.readiness.text())
                panel.configuration.source_mode.setCurrentIndex(panel.configuration.source_mode.findData('HEAD'))
                self.assertEqual(panel.revision.text(),'HEAD')
                self.assertEqual(panel.choices()['platform_backends']['ios'],'GitHub')
                self.assertTrue(panel.configuration.source_summary.isHidden())
                self.assertIn('local edits are excluded',panel.configuration.source_mode.toolTip())
                panel.plan=OtherProject(Path(directory)).make_plan();panel.start.setEnabled(True)
                panel.platform_backends['ios'].setCurrentText('Local fixture')
                self.assertIsNone(panel.plan);self.assertFalse(panel.start.isEnabled())
                with self.assertRaisesRegex(ValueError,'every selected platform'):
                    request(project.journey_capability,'validate',['ios'],[],backends={})
            finally:panel.close();self.app.processEvents()

    def test_single_settings_entry_and_whole_page_scroll(self):
        with TemporaryDirectory() as directory:
            window=ManagerWindow(Registry(Path(directory)/'registry'));window.resize(900,600);window.show()
            try:
                self.app.processEvents()
                visible=[w for w in window.findChildren(QPushButton) if w.isVisible() and w.text()=='Project settings…']
                self.assertEqual(visible,[window.project_settings])
                self.assertTrue(window.current_view.isAncestorOf(window.projects))
                self.assertNotIn('Project settings…',window.menu_actions)
            finally:window.close();self.app.processEvents()

    def test_run_fields_reject_secrets_and_unlisted_overrides(self):
        fields=[dict(id='notes',label='Notes',kind='multiline')]
        validate_fields(fields,dict(operations=['Test']))
        self.assertEqual(validate_overrides(fields,{'notes':'Unicode café'}),{'notes':'Unicode café'})
        with self.assertRaises(ValueError):validate_overrides(fields,{'auth.reference':'arbitrary'})
        with self.assertRaises(ValueError):validate_overrides(fields,{'notes':'Bearer synthetic-secret'})
        with self.assertRaises(ValueError):validate_fields([dict(fields[0],operations='Test')],dict(operations=['Test']))

    def test_late_defaults_preserve_edits_and_invalidate_review(self):
        from build_manager.run_fields_ui import RunFieldsView
        class Project:
            run_fields=[dict(id='notes',label='Notes',kind='multiline',operations=['Test']),
                        dict(id='group',label='Group',operations=['Test'])]
        view=RunFieldsView(Project());view.update_context('advanced',[],'Test')
        try:
            applied=[];view.defaults_loaded.connect(lambda:applied.append(True))
            view.controls['notes'].setPlainText('My run notes')
            view.results.put(({'notes':'Saved note','group':'Saved group'},None));view.loaded()
            self.assertEqual(view.values(),{'notes':'My run notes','group':'Saved group'})
            self.assertEqual(applied,[True])
            view.controls['notes'].clear()
            self.assertEqual(view.values()['notes'],'')
        finally:view.stop();view.close()

    def test_cli_forwards_per_platform_hosts_and_run_values(self):
        from unittest.mock import patch,MagicMock
        from contextlib import redirect_stdout,redirect_stderr
        from io import StringIO
        from build_manager.cli import main
        project=MagicMock();project.journey_capability=deepcopy(CAPABILITY)
        project.make_journey.return_value.identity='prepared'
        with TemporaryDirectory() as directory,patch('build_manager.bridge.ProjectBridge',return_value=project):
            args=['--registry',directory,'journey','--project','fixture','--goal','validate',
                  '--platform','ios','--execution','ios=GitHub','--run-value','notes=Café',
                  '--output',str(Path(directory)/'plan.json')]
            with redirect_stdout(StringIO()):self.assertEqual(main(args),0)
            project.make_journey.assert_called_once_with('validate',['ios'],[],revision='working-tree',
                release_tag='',backends={'ios':'GitHub'},run_overrides={'notes':'Café'})
            project.make_journey.reset_mock()
            args[args.index('ios=GitHub')]='android=GitHub'
            with redirect_stderr(StringIO()):self.assertEqual(main(args),1)
            project.make_journey.assert_not_called()
