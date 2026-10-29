"""An explicit consumer source root takes precedence over editable bootstrap paths."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class ImportPrecedenceTests(unittest.TestCase):
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
