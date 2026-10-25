"""Contracts exposed by native Windows acceptance."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from build_manager.history import recent_runs
from build_manager.profiles import save_json
from build_manager.ui import ReadHistory


class NativeFileTests(unittest.TestCase):
    def test_atomic_publication_retries_only_transient_windows_sharing_errors(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'state.json'
            real_replace = Path.replace
            sharing = PermissionError('reader holds destination')
            sharing.winerror = 32
            calls = []
            def replace(source, destination):
                calls.append(source)
                if len(calls) == 1:
                    raise sharing
                return real_replace(source, destination)
            windows = Mock(wraps=os)
            windows.name = 'nt'
            with patch('build_manager.profiles.os', windows), patch.object(Path, 'replace', replace):
                save_json(target, {'published': True})
            self.assertEqual(len(calls), 2)
            self.assertIn('true', target.read_text())
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_cancelled_history_does_not_open_another_report(self):
        with TemporaryDirectory() as folder:
            for name in ('first', 'second'):
                save_json(Path(folder) / name / 'result.json', dict(schema=1, status='passed', phases=[]))
            cancelled = Event()
            def read(path):
                cancelled.set()
                return dict(status='passed')
            with patch('build_manager.history.read_report', side_effect=read) as reader:
                self.assertEqual(len(recent_runs(folder, cancelled=cancelled.is_set)), 1)
                self.assertEqual(reader.call_count, 1)

    def test_history_worker_signals_completion_after_cancellation(self):
        from queue import Queue
        entered, release = Event(), Event()
        def read(*args):
            entered.set()
            release.wait(2)
            return []
        job = ReadHistory('.', Queue())
        with patch('build_manager.history.recent_runs', side_effect=read):
            thread = Thread(target=job.run)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                job.cancelled.set()
                self.assertFalse(job.done.is_set())
            finally:
                release.set()
                thread.join(2)
            self.assertTrue(job.done.is_set())
