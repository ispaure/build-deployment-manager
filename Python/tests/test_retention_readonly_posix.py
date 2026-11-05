"""Owned POSIX Go-cache removal; no real project caches or SDK state touched."""
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from build_manager import retention


@unittest.skipUnless(os.name=='posix' and os.geteuid()!=0,'POSIX non-root permission semantics')
class ReadonlyModuleCacheTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.temp=Path(temporary.name).resolve()
        self.root=self.temp/'owned';self.root.mkdir();self.marker=self.root/'.manager-cache';self.marker.touch()

    def restore_permissions(self):
        if self.root.exists():
            for root,dirs,files in os.walk(self.root,followlinks=False):
                Path(root).chmod(0o700)

    def test_actual_readonly_go_directory_and_file_are_removed_under_owned_marker(self):
        leaf=self.root/'modules/example.org@v1/pkg/decode_test.go';leaf.parent.mkdir(parents=True);leaf.write_bytes(b'owned module fixture')
        for directory in (leaf.parent,leaf.parent.parent):directory.chmod(0o555)
        leaf.chmod(0o444)
        try:
            retention.remove_tree(self.root,ownership_files=('.manager-cache',))
            self.assertFalse(self.root.exists())
        finally:self.restore_permissions()

    def test_writable_parent_permission_denial_is_not_reclassified_or_hidden(self):
        leaf=self.root/'decode_test.go';leaf.write_text('retained');error=PermissionError('synthetic ACL denial')
        original=os.unlink
        def denied(path,*args,**kwargs):
            if str(path).endswith('decode_test.go'):raise error
            return original(path,*args,**kwargs)
        with patch.object(retention.os,'unlink',side_effect=denied),patch.object(Path,'chmod') as chmod:
            with self.assertRaises(PermissionError) as caught:retention.remove_tree(self.root,ownership_files=('.manager-cache',))
        self.assertIs(caught.exception,error);chmod.assert_not_called();self.assertTrue(self.marker.exists());self.assertTrue(leaf.exists())

    def test_failed_retry_preserves_original_ownership_marker(self):
        parent=self.root/'module';parent.mkdir();leaf=parent/'decode_test.go';leaf.write_text('retained');parent.chmod(0o555)
        error=PermissionError('permanent denial');original=os.unlink
        def denied(path,*args,**kwargs):
            if str(path).endswith('decode_test.go'):raise error
            return original(path,*args,**kwargs)
        try:
            with patch.object(retention.os,'unlink',side_effect=denied),self.assertRaises(PermissionError):
                retention.remove_tree(self.root,ownership_files=('.manager-cache',))
            self.assertTrue(self.marker.exists());self.assertTrue(leaf.exists())
        finally:self.restore_permissions()

    def test_retry_never_chmods_linked_or_outside_parent(self):
        outside=self.temp/'outside';outside.mkdir();file=outside/'decode_test.go';file.write_text('retained');outside.chmod(0o555)
        link=self.root/'link';link.symlink_to(outside,target_is_directory=True)
        error=PermissionError('synthetic traversal denial')
        def attempt(path,*,onexc):onexc(os.unlink,str(link/'decode_test.go'),error)
        try:
            with patch.object(retention.shutil,'rmtree',side_effect=attempt),patch.object(Path,'chmod') as chmod,self.assertRaises(PermissionError):
                retention._remove_tree_once(self.root)
            chmod.assert_not_called();self.assertTrue(file.exists());self.assertEqual(stat.S_IMODE(outside.stat().st_mode),0o555)
        finally:outside.chmod(0o700)

    def test_top_level_parent_outside_selected_tree_is_not_modified(self):
        error=PermissionError('synthetic root removal denial')
        def attempt(path,*,onexc):onexc(os.rmdir,str(self.root),error)
        with patch.object(retention.shutil,'rmtree',side_effect=attempt),patch.object(Path,'chmod') as chmod,self.assertRaises(PermissionError):
            retention._remove_tree_once(self.root)
        chmod.assert_not_called();self.assertTrue(self.marker.exists())
