"""Workspace contention policy around shared advisory process locks."""
from contextlib import contextmanager
from pathlib import Path
from commonUtils.persistence.locking import file_lock


@contextmanager
def workspace_lock(path, *, timeout=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path, timeout=timeout) as acquired:
        if not acquired:
            raise RuntimeError('Another operation owns this workspace.')
        yield
