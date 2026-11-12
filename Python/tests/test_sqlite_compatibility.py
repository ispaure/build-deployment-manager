"""The manager consumes its own shared pin without adding a database workflow."""
from contextlib import closing
import importlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class SQLiteCompatibilityTests(unittest.TestCase):
    def test_pinned_shared_api_reads_filters_and_commits_in_own_environment(self):
        from commonUtils.integrations.sqlite import Database, Filter
        module = importlib.import_module(Database.__module__)
        shared = Path(__file__).resolve().parents[1] / "commonUtils"
        self.assertTrue(Path(module.__file__).resolve().is_relative_to(shared.resolve()))
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.db"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO records VALUES (1, 'before')")
            with Database(path) as db:
                row = db.page("records", filters=Filter("id", "eq", 1)).rows[0]
            with Database(path, writable=True) as db, db.transaction() as tx:
                tx.update(row.token, {"value": "after"})
            with Database(path) as db:
                self.assertEqual(db.page("records").rows[0]["value"], "after")

    def test_normal_empty_app_startup_uses_manager_pin(self):
        root = Path(__file__).resolve().parents[2]
        source = root / "Python"
        code = ("import sys; from pathlib import Path; import commonUtils; "
                "assert Path(commonUtils.__file__).resolve().parent == Path(sys.argv[1]).resolve(); "
                "from build_manager.app import main; "
                "result = main(['--registry', sys.argv[2], '--smoke-exit']); "
                "assert 'commonUtils.ui.sqlite_browser.window' not in sys.modules; "
                "raise SystemExit(result)")
        with TemporaryDirectory() as temporary:
            environment = dict(os.environ, PYTHONPATH=str(source), QT_QPA_PLATFORM="offscreen",
                               COMMONUTILS_STORAGE_ROOT=str(Path(temporary) / "shared"))
            result = subprocess.run([sys.executable, "-c", code, str(source / "commonUtils"),
                                     str(Path(temporary) / "registry")], cwd=root,
                                    env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
