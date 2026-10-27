"""A wrapper exiting first must not cut off its descendant's cleanup grace."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from build_manager.executor import stop_process


@unittest.skipIf(os.name == 'nt', 'POSIX process-group contract')
class ProcessCleanupTests(unittest.TestCase):
    def test_descendant_can_finish_cleanup_after_wrapper_exits(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ready, cleaned = root / 'ready', root / 'cleaned'
            child = ('import signal,time,sys;from pathlib import Path;'
                'signal.signal(signal.SIGTERM,lambda *_:(time.sleep(.15),'
                f'Path({str(cleaned)!r}).write_text("finished"),sys.exit(0)));'
                f'Path({str(ready)!r}).touch();time.sleep(30)')
            parent = ('import subprocess,sys,time;'
                f'subprocess.Popen([sys.executable,"-c",{child!r}]);time.sleep(30)')
            process = subprocess.Popen([sys.executable, '-c', parent], start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                stop_process(process, grace=1)
                self.assertEqual(cleaned.read_text(), 'finished')
            finally:
                if process.poll() is None:
                    stop_process(process, grace=.1)
