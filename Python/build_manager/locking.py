"""Workspace contention policy around shared advisory process locks."""
from contextlib import contextmanager
from pathlib import Path
from commonUtils.persistence.locking import file_lock


def operation_lock_path(workspace):
    """Keep an operation's lifetime lock outside its disposable directory."""
    workspace = Path(workspace)
    return workspace.parent / ('.' + workspace.name + '.operation.lock')


@contextmanager
def workspace_lock(path, *, timeout=0):
    path = Path(path)
    # Retained plans and adapters already name this logical operation lock.
    # Resolve it consistently for executors, resource locks and retention; an
    # open file inside the retired tree prevents deletion on Windows.
    if path.name == 'operation.lock':
        path = operation_lock_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path, timeout=timeout) as acquired:
        if not acquired:
            raise RuntimeError('Another operation owns this workspace.')
        yield
