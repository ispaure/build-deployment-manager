from link_fixtures import directory_link
"""Dedicated machine ownership, recovery and native-readiness boundaries."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from build_manager.profiles import save_json
from build_manager.vm import LinuxVM, WindowsVM
from build_manager.vm_bootstrap import windows_answer


class DedicatedVMTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.client = Mock(executable='prlctl')
        self.vm = LinuxVM(self.folder.name, self.client)
        self.vm.root.mkdir()
        storage = patch('build_manager.vm.shutil.disk_usage',return_value=Mock(free=64*1024**3))
        storage.start();self.addCleanup(storage.stop)
        self.record = dict(schema=1, name=self.vm.name, uuid='00000000-0000-0000-0000-000000000001',
                           bundle=str(self.vm.root / (self.vm.name + '.pvm')), state='installation-required')

    def owned(self, status='stopped', state='installation-required'):
        self.record['state'] = state
        save_json(self.vm.record, self.record)
        Path(self.record['bundle']).mkdir(exist_ok=True)
        self.client.inventory.return_value = [dict(name=self.vm.name, uuid=self.record['uuid'], status=status)]
        return patch.object(self.vm, 'run', return_value=json.dumps([dict(Home=self.record['bundle'])]))

    def test_same_name_without_receipt_is_not_adopted_or_started(self):
        self.client.inventory.return_value = [dict(name=self.vm.name, uuid=self.record['uuid'], status='running')]
        with patch.object(self.vm, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'conflicting'): self.vm.selected()
            run.assert_not_called()

    def test_matching_uuid_moved_outside_vm_directory_is_rejected(self):
        with self.owned(), patch.object(self.vm, 'run', return_value=json.dumps([dict(Home='/personal/guest.pvm')])):
            with self.assertRaisesRegex(ValueError, 'outside'): self.vm.selected()

    def test_existing_vm_reused_without_resetting_hardware_or_disks(self):
        with self.owned(), patch('build_manager.vm.platform.system', return_value='Darwin'), patch.object(self.vm, 'configure') as configure:
            result = self.vm.ensure()
            self.assertEqual(result['uuid'], self.record['uuid'])
            configure.assert_not_called()

    def test_unregistered_owned_bundle_is_registered_without_creating_a_new_disk(self):
        save_json(self.vm.record, self.record); Path(self.record['bundle']).mkdir()
        self.client.inventory.return_value = []
        with patch('build_manager.vm.platform.system', return_value='Darwin'), patch.object(self.vm, 'run') as run, patch.object(self.vm, 'status', return_value={'state':'stopped'}):
            self.vm.ensure()
            run.assert_called_once_with('register', self.record['bundle'])

    def test_partial_configuration_is_recovered_only_while_stopped(self):
        with self.owned(state='creating'), patch('build_manager.vm.platform.system', return_value='Darwin'), patch.object(self.vm, 'configure') as configure:
            self.vm.ensure(); configure.assert_called_once_with(self.record['uuid'])
            self.assertEqual(self.vm.receipt()['state'], 'installation-required')
        with self.owned(status='running', state='creating'), patch('build_manager.vm.platform.system', return_value='Darwin'), patch.object(self.vm, 'configure') as configure:
            with self.assertRaisesRegex(ValueError, 'partially'): self.vm.ensure()
            configure.assert_not_called()

    def test_missing_owned_guest_recreated_with_new_identity_without_accessing_other_guests(self):
        save_json(self.vm.record, self.record)
        self.client.inventory.return_value = [dict(name='Held Fedora', uuid='unrelated', status='running')]
        with patch('build_manager.vm.platform.system', return_value='Darwin'), patch.object(self.vm, 'configure'), patch.object(self.vm, 'run') as run, patch.object(self.vm, 'status', return_value={}):
            self.vm.ensure()
            self.assertNotEqual(self.vm.receipt()['uuid'], self.record['uuid'])
            self.assertEqual(run.call_args.args[:2], ('create', self.vm.name))
            self.assertNotIn('unrelated', str(run.call_args))

    def test_media_mismatch_fails_before_hypervisor_mutation(self):
        media = Path(self.folder.name) / 'example.iso'; media.write_bytes(b'incorrect-media')
        with patch.object(self.vm, 'ensure') as ensure:
            with self.assertRaisesRegex(ValueError, 'checksum'): self.vm.initialize(media, '0' * 64)
            ensure.assert_not_called()

    def test_windows_unattended_never_wipes_previously_started_guest(self):
        vm = WindowsVM(self.folder.name, self.client)
        with patch.object(vm, 'ensure'), patch.object(vm, 'selected', return_value=(dict(ever_started=True),dict(status='stopped'))), patch.object(vm, 'initialize') as initialize:
            with self.assertRaisesRegex(ValueError, 'never-started'): vm.initialize_unattended('fixture.iso','0'*64)
            initialize.assert_not_called()

    def test_readiness_rejects_wrong_os_old_python_and_missing_git(self):
        with self.owned(status='running'):
            for proof in [dict(system='Windows', python_version=[3,14],git='git'),
                          dict(system='Linux', python_version=[3,11],git='git'),
                          dict(system='Linux', python_version=[3,14],git=None)]:
                with patch.object(self.vm,'probe',return_value=proof):
                    with self.assertRaisesRegex(ValueError,'incomplete'): self.vm.readiness()
            self.assertEqual(self.vm.receipt()['state'],'installation-required')

    def test_storage_and_receipt_symlinks_are_rejected(self):
        directory_link(self.vm.record, Path(self.folder.name)/'elsewhere')
        with self.assertRaisesRegex(ValueError,'symlink'): self.vm.receipt()

    def test_windows_answer_keeps_security_and_does_not_enable_developer_mode(self):
        import xml.etree.ElementTree as ET
        text=windows_answer('synthetic<&password')
        ET.fromstring(text)
        self.assertIn('synthetic&lt;&amp;password',text)
        self.assertNotIn('ExecutionPolicy',text)
        self.assertNotIn('DeveloperMode',text)
        self.assertNotIn('LabConfig',text)
        self.assertIn('<LogonCount>1</LogonCount>',text)

    def test_corrupt_cached_windows_installer_stops_before_seed_creation(self):
        from build_manager.vm_bootstrap import windows_helpers
        folder=Path(self.folder.name)/'media';folder.mkdir()
        (folder/'python-arm64.exe').write_bytes(b'corrupt installer')
        with patch('build_manager.vm_bootstrap.urllib.request.urlopen') as download:
            with self.assertRaisesRegex(ValueError,'checksum mismatch'): windows_helpers(self.folder.name)
            download.assert_not_called()

    def test_windows_symlink_policy_requires_approval_and_survives_bundle_removal(self):
        vm = WindowsVM(self.folder.name, self.client)
        with patch.object(vm, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Explicit approval'):
                vm.enable_symlink_testing()
            run.assert_not_called()
        self.assertFalse(vm.symlink_policy())
        record = dict(uuid=self.record['uuid'])
        with patch.object(vm, 'selected', return_value=(record, dict(status='running'))), patch.object(vm, 'status', return_value={}), patch.object(vm, 'run') as run:
            vm.enable_symlink_testing(approved=True)
            self.assertEqual(run.call_args.args[:3], ('exec', record['uuid'], 'reg.exe'))
            self.assertIn('AllowDevelopmentWithoutDevLicense', run.call_args.args)
        self.assertTrue(WindowsVM(self.folder.name, self.client).symlink_policy())
        from build_manager.vm_bootstrap import windows_bootstrap
        self.assertNotIn('AllowDevelopmentWithoutDevLicense', windows_bootstrap())
        self.assertIn('AllowDevelopmentWithoutDevLicense', windows_bootstrap(developer_mode=vm.symlink_policy()))

    def test_windows_initializer_consumes_persisted_symlink_policy(self):
        vm = WindowsVM(self.folder.name, self.client)
        save_json(vm.root / 'windows-policy.json', dict(schema=1, developer_mode_approved=True))
        record = dict(uuid=self.record['uuid'], media='fixture.iso', media_sha256='0'*64)
        with patch.object(vm, 'ensure'), patch.object(vm, 'selected', return_value=(record, dict(status='stopped'))), patch.object(vm, 'initialize'), patch.object(vm, 'run'), patch.object(vm, 'status'), patch('build_manager.vm_bootstrap.windows_seed', return_value=Path('seed.iso')) as seed:
            vm.initialize_unattended('fixture.iso', '0'*64)
        seed.assert_called_once_with(vm.root, developer_mode=True)

    def test_low_host_storage_stops_before_creating_a_guest(self):
        self.client.inventory.return_value=[]
        with patch('build_manager.vm.platform.system',return_value='Darwin'),patch('build_manager.vm.shutil.disk_usage',return_value=Mock(free=1024)),patch.object(self.vm,'run') as run:
            with self.assertRaisesRegex(ValueError,'24 GiB'):self.vm.ensure()
            run.assert_not_called()

    def test_guest_control_requires_explicit_approval_and_keeps_individual_sharing_off(self):
        with patch.object(self.vm,'run') as run:
            with self.assertRaisesRegex(ValueError,'Explicit approval'):self.vm.enable_guest_commands()
            run.assert_not_called()
        with self.owned() as run:
            self.vm.enable_guest_commands(approved=True)
            mutations=[call.args for call in run.call_args_list if call.args[0]=='set']
            self.assertEqual(mutations[-1],('set',self.record['uuid'],'--isolate-vm','off'))
            self.assertIn('--shared-clipboard',str(mutations[:-1]))
            self.assertIn('--shf-host',str(mutations[:-1]))

    def test_cached_recreation_recipe_uses_matching_initializer_and_clears_pending_state(self):
        recipe=dict(kind='fedora-cloud',media='/owned/media.qcow2',sha256='0'*64)
        self.record['restore_recipe']=recipe;save_json(self.vm.record,self.record)
        with patch.object(self.vm,'_ensure_hardware',return_value={}),patch.object(self.vm,'initialize_cloud',return_value={'state':'first-boot-required'}) as initialize:
            self.vm.ensure()
            initialize.assert_called_once_with(recipe['media'],recipe['sha256'])
            self.assertNotIn('restore_recipe',self.vm.receipt())


class VMUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_background_setup_keeps_ui_responsive_and_prevents_worker_destruction(self):
        from threading import Event
        import time
        from build_manager.vm_ui import VMDialog
        entered,release=Event(),Event()
        def ensure():
            entered.set();release.wait(5)
            return dict(name='Synthetic Linux',state='stopped',setup='installation-required',requirements='Test tools',storage='/owned/VM')
        with TemporaryDirectory() as directory:
            (Path(directory)/'Python/build_manager').mkdir(parents=True)
            dialog=VMDialog(checkout=directory)
            with patch('build_manager.vm.LinuxVM') as factory:
                factory.return_value.ensure.side_effect=ensure
                dialog.launch('ensure')
                self.assertTrue(entered.wait(2));self.assertFalse(dialog.kind.isEnabled())
                dialog.reject();self.assertTrue(dialog.worker.isRunning())
                release.set()
                deadline=time.monotonic()+3
                while dialog.worker.isRunning() and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.01)
                self.app.processEvents()
                self.assertTrue(dialog.kind.isEnabled())
                self.assertIn('Synthetic Linux',dialog.details.text())
                dialog.reject()


if __name__ == '__main__': unittest.main()
