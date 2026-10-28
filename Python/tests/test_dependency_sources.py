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
