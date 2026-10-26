"""Real GUI-to-CLI workflow pause/review/resume with harmless processes."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QFileDialog
from build_manager import Plan,Phase
from build_manager.ui import ManagerPanel


class WorkflowUITests(unittest.TestCase):
    def test_real_chain_pauses_for_review_and_resumes_in_same_run(self):
        app=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as directory:
            root=Path(directory);artifact=root/'artifact';effect=root/'effect'
            class Project:
                interpreter=sys.executable;runner_directory=Path.cwd();results_directory=root/'results'
                description='Workflow fixture';operations=('Prepare and review',);platforms=('fixture',)
                def backend_options(self,*_):return ('Local',)
                def make_plan(self,*_,**__):
                    return Plan('Fixture','chain',{'commit':'fixed'},(
                        Phase('prepare',(sys.executable,'-c',f'from pathlib import Path;Path({str(artifact)!r}).write_text("prepared")'),str(root),artifacts=(str(artifact),)),
                        Phase('reviewed-effect',(sys.executable,'-c',f'from pathlib import Path;Path({str(effect)!r}).write_text("accepted")'),str(root),dependencies=('prepare',),effect='upload')),
                        str(root/'workspace'))
            panel=ManagerPanel(Project());panel.inspect_plan()
            deadline=time.monotonic()+15
            while panel.preparing:app.processEvents();time.sleep(.01);self.assertLess(time.monotonic(),deadline)
            panel.run_plan()
            def finish():
                while panel.cancel.isEnabled():app.processEvents();time.sleep(.01);self.assertLess(time.monotonic(),deadline)
                return json.loads(panel.result.read_text())
            first=finish();self.assertEqual(first['status'],'awaiting_review');self.assertFalse(effect.exists())
            self.assertTrue(panel.continue_run.isEnabled())
            with patch.object(panel,'confirm_continuation',return_value=False):
                panel.continue_run.click()
                while panel.reviewing:
                    app.processEvents();time.sleep(.005);self.assertLess(time.monotonic(),deadline)
            self.assertFalse(effect.exists())
            artifact.write_text('changed after preparation')
            with patch.object(panel, 'confirm_continuation', return_value=True) as approval:
                panel.continue_run.click()
                while panel.reviewing:
                    app.processEvents();time.sleep(.005);self.assertLess(time.monotonic(),deadline)
            approval.assert_not_called()
            self.assertIn('missing or changed', panel.status.text())
            self.assertFalse(effect.exists())
            artifact.write_text('prepared')
            original_result = panel.result
            with patch.object(QFileDialog,'getOpenFileName',side_effect=AssertionError('direct continuation must not browse')),patch.object(panel,'confirm_continuation',return_value=True):
                panel.continue_run.click()
                while panel.reviewing:
                    app.processEvents();time.sleep(.005);self.assertLess(time.monotonic(),deadline)
            last = finish()
            self.assertEqual(last['status'],'passed');self.assertTrue(effect.exists())
            self.assertEqual(panel.result, original_result)
            self.assertEqual(last['phases'][0]['started_at'], first['phases'][0]['started_at'])
            panel.close()
