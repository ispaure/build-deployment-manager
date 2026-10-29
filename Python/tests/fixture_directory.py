"""Disposable test directories wait briefly for Windows executable/file release."""
import os
from tempfile import TemporaryDirectory as StandardTemporaryDirectory
import time


class TemporaryDirectory(StandardTemporaryDirectory):
    def cleanup(self):
        deadline = time.monotonic() + 3
        while True:
            try:
                return super().cleanup()
            except PermissionError as error:
                if os.name != 'nt' or error.winerror not in (5, 32, 33) or time.monotonic() >= deadline:
                    raise
                # Windows can retain a just-exited executable mapping briefly.
                # A persistent lock still fails; this never abandons the tree.
                time.sleep(.05)
