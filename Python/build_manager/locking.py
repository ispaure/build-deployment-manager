"""Non-blocking advisory workspace locks, released on process exit."""
from contextlib import contextmanager
from pathlib import Path
import os
import time


@contextmanager
def workspace_lock(path, *, timeout=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            # Reading an already locked byte fails before the second locking
            # call on Windows. Size inspection does not enter that byte range.
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Another operation owns this workspace.') from None
                    time.sleep(.02)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Another operation owns this workspace.') from None
                    time.sleep(.02)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
