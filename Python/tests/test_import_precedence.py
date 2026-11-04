"""Explicit project context preserves interpreter roots in either import order."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ImportPrecedenceTests(unittest.TestCase):
    def test_unknown_dependency_context_fails_before_loading_shared_or_ui_modules(self):
        source = Path(__file__).resolve().parents[1]
        code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                'import build_manager')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(source)],
            env=dict(os.environ, BUILD_MANAGER_DEPENDENCIES='unknown'),
            capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('BUILD_MANAGER_DEPENDENCIES must be manager or project', result.stderr)

    def test_project_context_preserves_explicit_dependency_in_both_import_orders(self):
        source = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            package = Path(folder) / 'commonUtils'
            package.mkdir()
            (package / '__init__.py').write_text('__path__ = ' + repr([str(source / 'commonUtils')]))
            for imports in ('import build_manager; import commonUtils',
                            'import commonUtils; import build_manager'):
                with self.subTest(imports=imports):
                    code = ('import sys; sys.path[:0] = sys.argv[1:3]; ' + imports + '; '
                        'from pathlib import Path; '
                        'assert Path(commonUtils.__file__).parent == Path(sys.argv[1])/"commonUtils"; '
                        'from build_manager import identity; '
                        'identity.checkout_identity = lambda root: str(root); '
                        'assert identity.capture_engine_source_identity()["commonUtils"] == '
                        'str(Path(commonUtils.__file__).resolve().parent); '
                        'assert not any(k.startswith(("PySide6", "PyQt", "logistics_build")) for k in sys.modules)')
                    result = subprocess.run([sys.executable, '-I', '-c', code, folder, str(source)],
                        env=dict(os.environ, BUILD_MANAGER_DEPENDENCIES='project'),
                        capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_preloaded_explicit_consumer_commonutils_is_preserved_by_manager_import(self):
        source = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            package = Path(folder) / 'commonUtils'
            package.mkdir()
            (package / '__init__.py').write_text('__path__ = ' + repr([str(source / 'commonUtils')]))
            code = ('import sys; sys.path[:0] = sys.argv[1:3]; '
                    'import commonUtils; import build_manager; from pathlib import Path; '
                    'assert Path(commonUtils.__file__).parent == Path(sys.argv[1])/"commonUtils", commonUtils.__file__')
            result = subprocess.run([sys.executable, '-I', '-c', code, folder, str(source)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_standalone_manager_still_uses_its_own_pinned_commonutils(self):
        source = Path(__file__).resolve().parents[1]
        code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                'import build_manager, commonUtils; from pathlib import Path; '
                'assert Path(commonUtils.__file__).parent == Path(sys.argv[1])/"commonUtils", commonUtils.__file__')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(source)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
