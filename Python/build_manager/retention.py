"""Bounded retention for explicitly owned directories, respecting active leases."""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import stat
import time

from .locking import workspace_lock
from commonUtils.filesystem.links import is_junction


def linked(path):
    """Both symlinks and Windows junctions redirect ownership boundaries."""
    return path.is_symlink() or is_junction(path)


def remove_tree(path):
    """Remove caller-owned scratch, bounding Windows executable-release waits."""
    deadline = time.monotonic() + 3
    while True:
        try:
            return _remove_tree_once(path)
        except PermissionError as error:
            if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33)
                    or time.monotonic() >= deadline):
                raise
            time.sleep(.05)


def _remove_tree_once(path):
    path = Path(path)
    def readonly(function, name, error):
        target = Path(name)
        if (os.name != 'nt' or not isinstance(error, PermissionError) or linked(target)
                or target.stat().st_mode & stat.S_IWRITE):
            raise error
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        function(name)
    if path.is_symlink():
        path.unlink()
    elif is_junction(path):
        path.rmdir()
    else:
        shutil.rmtree(path, onexc=readonly)


def durable_hold(path, owner, *, days=7, release=False):
    """Retain paused outputs without changing source/snapshot contents."""
    from .profiles import load_profile, save_profile
    path = Path(path)
    record = path.parent / ('.' + path.name + '.manager-holds.json')
    with workspace_lock(record.with_suffix('.lock')):
        values = load_profile(record)
        leases = values.setdefault('leases', {})
        if release:
            leases.pop(owner, None)
        else:
            leases[owner] = time.time() + days * 86400
        save_profile(record, values, allowed={'leases'})


def pinned(path):
    from .profiles import load_profile
    path = Path(path)
    record = path.parent / ('.' + path.name + '.manager-holds.json')
    try:
        leases = load_profile(record).get('leases', {})
        if any(expires > time.time() for expires in leases.values()):
            return True
    except (OSError, ValueError, TypeError):
        return True # Unreadable ownership state is protected, never swept.
    # A pin anywhere inside an owned tree also protects its enclosing snapshot.
    for folder, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not linked(Path(folder) / name)]
        if '.keep' in files:
            return True
    return False


def allocated_bytes(path):
    """Measure owned tree allocation without following directory or file links."""
    total = 0
    pending = [Path(path)]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or (os.name == 'nt' and linked(Path(entry.path))):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
                else:
                    total += getattr(info, 'st_blocks', (info.st_size + 511) // 512) * 512
    return total


def prune(root, *, eligible, keep=3, age_days=1, apply=False, lock_path=None, now=None, order_key=None,
          max_bytes=None, grace_days=0, last_used=None):
    """Keep newest/pinned/locked trees; an optional budget can evict recent ones.

    A budget is soft: newest entries, active leases, pins and the grace period
    always win. Preview and apply use the same oldest-first pressure selection.
    """
    root = Path(root)
    if keep < 1 or age_days < 0 or grace_days < 0 or (max_bytes is not None and max_bytes < 0):
        raise ValueError('Retention requires at least one retained entry and a nonnegative age.')
    if not root.exists():
        return []
    if any(linked(part) for part in (root, *root.parents)):
        return []
    now = time.time() if now is None else now
    last_used = last_used or (lambda p: p.stat().st_mtime)
    rows = []
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    with workspace_lock(root / '.retention.lock'):
        entries = sorted((p for p in root.iterdir() if not linked(p) and p.is_dir() and eligible(p)),
                         key=order_key or (lambda p: (last_used(p), p.name)), reverse=True)
        sizes = {path: allocated_bytes(path) for path in entries} if max_bytes is not None else {}
        remaining = sum(sizes.values())
        # Oldest first makes the pressure policy retain the most useful caches.
        candidates = list(reversed(entries[keep:])) if max_bytes is not None else entries[keep:]
        for path in candidates:
            try:
                with workspace_lock(lock_path(path)):
                    age = now - last_used(path)
                    pressure = max_bytes is not None and remaining > max_bytes
                    if age < grace_days * 86400 or (age < age_days * 86400 and not pressure) or pinned(path):
                        continue
                    # Recheck caller ownership after acquiring the entry lock.
                    if linked(path) or not eligible(path):
                        continue
                    rows.append(str(path))
                    remaining -= sizes.get(path, 0)
                    if apply:
                        remove_tree(path)
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
    if not root.is_dir() or any(linked(p) for p in (root, *root.parents)):
        return []
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    rows = []
    with workspace_lock(root / '.retention.lock'):
        for path in sorted(root.iterdir()):
            if linked(path) or not path.is_dir() or not eligible(path):
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
    if not root.is_dir() or any(linked(p) for p in (root, *root.parents)):
        raise ValueError('Cleanup root is missing or linked; nothing was deleted.')
    lock_path = lock_path or (lambda path: root / ('.' + path.name + '.retention.lock'))
    removed, skipped = [], []
    with workspace_lock(root / '.retention.lock'):
        for name in dict.fromkeys(names):
            if name in ('', '.', '..') or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Cleanup accepts owned direct child names only.')
            path = root / name
            if linked(path) or not path.is_dir() or not eligible(path):
                skipped.append(name + ': no longer an owned output')
                continue
            try:
                with workspace_lock(lock_path(path)):
                    if pinned(path):
                        skipped.append(name + ': pinned by .keep')
                        continue
                    remove_tree(path)
                    removed.append(str(path))
            except (RuntimeError, OSError) as error:
                skipped.append(name + ': ' + str(error))
    return dict(removed=removed, skipped=skipped)
