"""Bounded retention for explicitly owned directories, respecting active leases."""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import time

from .locking import workspace_lock


def pinned(path):
    # A pin anywhere inside an owned tree also protects its enclosing snapshot.
    for folder, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()]
        if '.keep' in files:
            return True
    return False


def prune(root, *, eligible, keep=3, age_days=1, apply=False, lock_path=None, now=None, order_key=None):
    """Keep newest entries plus recent/pinned/locked trees. Never follow root links."""
    root = Path(root)
    if keep < 1 or age_days < 0:
        raise ValueError('Retention requires at least one retained entry and a nonnegative age.')
    if not root.exists():
        return []
    if any(part.is_symlink() for part in (root, *root.parents)):
        return []
    now = time.time() if now is None else now
    rows = []
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    with workspace_lock(root / '.retention.lock'):
        entries = sorted((p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and eligible(p)),
                         key=order_key or (lambda p: (p.stat().st_mtime, p.name)), reverse=True)
        for path in entries[keep:]:
            try:
                with workspace_lock(lock_path(path)):
                    if now - path.stat().st_mtime < age_days * 86400 or pinned(path):
                        continue
                    rows.append(str(path))
                    if apply:
                        shutil.rmtree(path)
            except RuntimeError:
                # A running build or snapshot materializer owns this entry.
                continue
    return rows


@contextmanager
def lease(path):
    """Mark a build active and refresh its retention age even after failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with workspace_lock(path.parent / ('.' + path.name + '.retention.lock')):
        path.mkdir(exist_ok=True)
        os.utime(path, None)
        try:
            yield
        finally:
            if path.exists():
                os.utime(path, None)


def owned_entries(root, *, eligible, lock_path=None):
    """List explicitly owned outputs; manual cleanup ignores automatic age limits."""
    root = Path(root)
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        return []
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    rows = []
    with workspace_lock(root / '.retention.lock'):
        for path in sorted(root.iterdir()):
            if path.is_symlink() or not path.is_dir() or not eligible(path):
                continue
            reason = ''
            try:
                with workspace_lock(lock_path(path)):
                    if pinned(path):
                        reason = 'Pinned by .keep'
            except RuntimeError:
                reason = 'In use by an active operation'
            rows.append(dict(name=path.name, path=str(path), protected=reason))
    return rows


def delete_owned(root, names, *, eligible, lock_path=None):
    """Revalidate explicit direct children while holding the retention and lease locks."""
    root = Path(root)
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Cleanup root is missing or linked; nothing was deleted.')
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    removed, skipped = [], []
    with workspace_lock(root / '.retention.lock'):
        for name in dict.fromkeys(names):
            if name in ('', '.', '..') or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Cleanup accepts owned direct child names only.')
            path = root / name
            if path.is_symlink() or not path.is_dir() or not eligible(path):
                skipped.append(name + ': no longer an owned output')
                continue
            try:
                with workspace_lock(lock_path(path)):
                    if pinned(path):
                        skipped.append(name + ': pinned by .keep')
                        continue
                    shutil.rmtree(path)
                    removed.append(str(path))
            except (RuntimeError, OSError) as error:
                skipped.append(name + ': ' + str(error))
    return dict(removed=removed, skipped=skipped)
