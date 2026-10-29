"""Exact committed transfer owns mechanics independently of any consumer."""
import io
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
import zipfile
from build_manager.dependency_sources import archive, verify


class DependencySourceTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.manager = self.root/'manager'
        self.shared = self.manager/'Python/commonUtils'
        self.shared.mkdir(parents=True)
        self.project = self.root/'project'
        self.project.mkdir()
        self.command(self.shared, 'init', '--quiet')
        (self.shared/'library.py').write_text('SHARED = True')
        self.command(self.shared, 'add', 'library.py')
        self.commit(self.shared)
        shared = self.command(self.shared, 'rev-parse', 'HEAD')
        self.command(self.manager, 'init', '--quiet')
        (self.manager/'public.py').write_text('PUBLIC = True')
        self.command(self.manager, 'add', 'public.py')
        self.command(self.manager, 'update-index', '--add', '--cacheinfo', '160000,'+shared+',Python/commonUtils')
        self.commit(self.manager)
        self.pin = self.command(self.manager, 'rev-parse', 'HEAD')


    def command(self, root, *args):
        return subprocess.check_output(['git','-C',str(root),*args],text=True,stderr=subprocess.PIPE).strip()

    def commit(self, root):
        self.command(root, '-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','fixture')

    def test_archives_preserve_pinned_git_sources_without_private_checkout_files(self):
        (self.manager/'private-credential').write_text('synthetic-private-input')
        for kind in ('zip','tar'):
            with self.subTest(kind=kind):
                with TemporaryDirectory() as scratch:
                    payload = archive(self.manager, self.pin, kind, scratch)
                if kind=='zip':
                    with zipfile.ZipFile(io.BytesIO(payload)) as data: names=data.namelist()
                else:
                    with tarfile.open(fileobj=io.BytesIO(payload)) as data: names=data.getnames()
                self.assertIn('public.py',names)
                self.assertIn('Python/commonUtils/library.py',names)
                self.assertIn('.git/HEAD',names)
                self.assertIn('.git/refs/' if kind=='zip' else '.git/refs',names)
                self.assertNotIn('private-credential',names)

    def test_wrong_pin_and_modified_tracked_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'dependency pin'):
            verify(self.manager, '0' * 40)
        (self.manager / 'public.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Commit manager'):
            verify(self.manager, self.pin)

    def test_invalid_kind_never_creates_transfer_sources(self):
        scratch = self.root / 'scratch'
        scratch.mkdir()
        with self.assertRaises(ValueError):
            archive(self.manager, self.pin, 'unsupported', scratch)
        self.assertFalse(list(scratch.iterdir()))

    def test_explicit_local_test_capture_includes_public_edits_and_rejects_tampering(self):
        from build_manager.dependency_sources import local_test_identity, verify_local_test_source
        (self.manager / 'public.py').write_text('PUBLIC = "working"')
        added = self.manager / 'Python/build_manager/new_test_helper.py'
        added.parent.mkdir(parents=True)
        added.write_text('NEW = True')
        (self.manager / 'private-credential').write_text('never transfer')
        identity = local_test_identity(self.manager, self.pin)
        with TemporaryDirectory() as scratch:
            with self.assertRaisesRegex(ValueError, 'Commit manager'):
                archive(self.manager, self.pin, 'zip', scratch)
        with TemporaryDirectory() as scratch:
            payload = archive(self.manager, self.pin, 'zip', scratch, working_tree=identity['fingerprint'])
        with TemporaryDirectory() as extracted:
            with zipfile.ZipFile(io.BytesIO(payload)) as data:
                self.assertNotIn('private-credential', data.namelist())
                self.assertIn('Python/build_manager/new_test_helper.py', data.namelist())
                data.extractall(extracted)
            actual = verify_local_test_source(extracted, self.pin, identity['fingerprint'])
            self.assertEqual(actual, identity)
            (Path(extracted) / 'public.py').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'differs'):
                verify_local_test_source(extracted, self.pin, identity['fingerprint'])
        with TemporaryDirectory() as scratch:
            with self.assertRaisesRegex(ValueError, 'changed after planning'):
                archive(self.manager, self.pin, 'tar', scratch, working_tree='0' * 64)

    def test_local_test_capture_keeps_commonutils_at_its_committed_pin(self):
        from build_manager.dependency_sources import local_test_identity
        (self.shared / 'library.py').write_text('SHARED = "unreviewed"')
        with self.assertRaisesRegex(ValueError, 'Commit manager'):
            local_test_identity(self.manager, self.pin)
