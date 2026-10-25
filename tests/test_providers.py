"""Unsupported stores fail before credentials/transport; host policy is explicit."""
import sys
from unittest.mock import Mock
import unittest
from build_manager import Phase,Plan,Executor
from build_manager.providers import settings_rows,require_provider


class ProviderCapabilityTests(unittest.TestCase):
    def test_future_stores_fail_before_any_credential_or_transport_access(self):
        transport=Mock();credentials=Mock()
        for provider in ('app-store','google-play'):
            with self.assertRaisesRegex(ValueError,'not implemented'):
                phase=Phase('future',(sys.executable,'-c','raise AssertionError'),'.',effect='publish',provider=provider)
                credentials();transport();Executor().run(Plan('fixture','future',{},(phase,),'.'),'unused')
        transport.assert_not_called();credentials.assert_not_called()
        rows=settings_rows(('ios','android'))
        self.assertTrue(all(row['read_only'] and row['value'].startswith('Not implemented') for row in rows.values()))
        self.assertEqual(settings_rows(('blender',)),{})
        for provider in ('testflight','firebase','github'):require_provider(provider)


    def test_actual_cli_rejects_crafted_store_plan_before_creating_run(self):
        import json,subprocess
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root=Path(directory);path=root/'plan.json'
            path.write_text(json.dumps(dict(project='fixture',operation='future store',source={},workspace=str(root/'workspace'),
                phases=[dict(id='store',argv=[sys.executable,'-c','raise AssertionError("must not execute")'],cwd=str(root),provider='app-store',effect='publish')])))
            result=subprocess.run([sys.executable,'-m','build_manager',str(path),'--output',str(root/'result')],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertIn('not implemented',result.stdout)
            self.assertFalse((root/'result').exists())

    def test_actual_settings_ui_shows_disabled_status_without_credential_prompts(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from build_manager.ui import SettingsDialog
        app=QApplication.instance() or QApplication([])
        class Project:
            def settings_view(self):return settings_rows(('ios','android'))
        dialog=SettingsDialog(Project())
        for key in ('distribution.app-store','distribution.google-play'):
            self.assertIn(key,dialog.read_only)
            self.assertTrue(dialog.controls[key].text().startswith('Not implemented'))
        dialog.close();app.processEvents()
