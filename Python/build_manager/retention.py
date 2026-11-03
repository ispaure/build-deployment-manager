"""Bounded retention for explicitly owned directories, respecting active leases."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import math
import os
import shutil
import stat
import time

from .locking import workspace_lock
from commonUtils.filesystem.links import is_junction
from commonUtils.filesystem.native_paths import native_path


def linked(path):
    """Both symlinks and Windows junctions redirect ownership boundaries."""
    return path.is_symlink() or is_junction(path)


def remove_tree(path, *, ownership_files=()):
    """Remove caller-owned scratch, bounding Windows executable-release waits."""
    deadline = time.monotonic() + 3
    while True:
        try:
            return (_remove_owned_tree_once(path, ownership_files) if ownership_files
                    else _remove_tree_once(path))
        except PermissionError as error:
            if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33)
                    or time.monotonic() >= deadline):
                raise
            time.sleep(.05)


def _remove_owned_tree_once(path, ownership_files):
    """Keep ownership proof until bulk removal finishes, including hard stops."""
    path = native_path(path)
    names = set(ownership_files)
    if any(not isinstance(name, str) or name in {'', '.', '..'} or '/' in name or '\\' in name for name in names):
        raise ValueError('Ownership proof must name direct files only.')
    if any(linked(part) for part in (path, *path.parents)):
        raise ValueError('Owned removal refuses linked directories.')
    for name in names:
        marker = path / name
        if linked(marker) or not marker.is_file():
            raise ValueError('Ownership proof changed before removal.')
    original = path.stat()
    try:
        for child in path.iterdir():
            if child.name not in names:
                _remove_tree_once(child)
        for name in names:
            _remove_tree_once(path / name)
        path.rmdir()
    except BaseException:
        # Failed cleanup must not make an old tree look recently used.
        try:
            current = path.stat()
            if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino) and not linked(path):
                os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        except OSError:
            pass
        raise


def _remove_tree_once(path):
    path = native_path(path)
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
    elif path.is_file():
        try:
            path.unlink()
        except PermissionError as error:
            readonly(os.unlink, str(path), error)
    else:
        shutil.rmtree(path, onexc=readonly)


def set_workflow_hold(path, owner, *, days=7):
    _update_workflow_hold(path, owner, release=False, days=days)


def release_workflow_hold(path, owner):
    _update_workflow_hold(path, owner, release=True)


def _update_workflow_hold(path, owner, *, release, days=7):
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


def durable_hold(path, owner, *, days=7, release=False):
    """Compatibility entry point for project retention policies."""
    if release:
        return release_workflow_hold(path, owner)
    return set_workflow_hold(path, owner, days=days)


def has_retention_protection(path):
    return bool(protection_reason(path))


def _hold_expirations(record):
    from .profiles import load_profile
    if linked(record):
        raise ValueError('Linked workflow hold record.')
    leases = load_profile(record).get('leases', {})
    if not isinstance(leases, dict) or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 for value in leases.values()):
        raise ValueError('Invalid workflow hold expiry.')
    return leases.values()


def protection_reason(path):
    """Explain persistent protection separately from an active operation lease."""
    path = Path(path)
    record = path.parent / ('.' + path.name + '.manager-holds.json')
    try:
        expires = max(_hold_expirations(record), default=0)
        if expires > time.time():
            until = datetime.fromtimestamp(expires, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            return 'Retained for workflow review/reconciliation until ' + until
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        return 'Unreadable workflow hold; protected' # Never sweep uncertain ownership.
    try:
        return 'Pinned by .keep' if has_keep_marker(path) else ''
    except OSError:
        return 'Unreadable pin state; protected'


def has_keep_marker(path):
    """User pins also cover rebuildable caches; workflow holds cover evidence."""
    # A pin anywhere inside an owned tree also protects its enclosing snapshot.
    def unreadable(error):
        raise error
    for folder, directories, files in os.walk(path, followlinks=False, onerror=unreadable):
        directories[:] = [name for name in directories if not linked(Path(folder) / name)]
        if '.keep' in files:
            return True
    return False


def nested_workflow_hold_reason(path):
    """A disposable enclosing checkout must not swallow its retained children."""
    def unreadable(error):
        raise error
    try:
        for folder, directories, files in os.walk(path, followlinks=False, onerror=unreadable):
            directories[:] = [name for name in directories if not linked(Path(folder) / name)]
            for name in files:
                if not name.startswith('.') or not name.endswith('.manager-holds.json'):
                    continue
                record = Path(folder) / name
                if linked(record):
                    return 'Unreadable nested workflow hold; protected'
                if any(expires > time.time() for expires in _hold_expirations(record)):
                    return 'Contains retained workflow outputs; protected'
    except (OSError, ValueError, TypeError, AttributeError):
        return 'Unreadable nested workflow hold; protected'
    return ''


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
          max_bytes=None, grace_days=0, last_used=None, protection=None, ownership_files=()):
    """Keep newest/pinned/locked trees; an optional budget can evict recent ones.

    A budget is soft: newest entries, active leases, pins and the grace period
    always win. Preview and apply use the same oldest-first pressure selection.
    """
    root = Path(root)
    if keep < 0 or age_days < 0 or grace_days < 0 or (max_bytes is not None and max_bytes < 0):
        raise ValueError('Retention requires nonnegative count, age and budget.')
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
                    if (age < grace_days * 86400 or (age < age_days * 86400 and not pressure)
                            or has_retention_protection(path) or protection and protection(path)):
                        continue
                    # Recheck caller ownership after acquiring the entry lock.
                    if (any(linked(part) for part in (path, *path.parents))
                            or not path.is_dir() or not eligible(path)):
                        continue
                    rows.append(str(path))
                    remaining -= sizes.get(path, 0)
                    if apply:
                        remove_tree(path, ownership_files=ownership_files)
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


def prune_cache_groups(groups, *, age_days, max_bytes, grace_days=0, apply=False, now=None):
    """Share a cache budget across declared roots without relaxing their locks.

    Each group uses prune's ownership/pin checks. Revalidate the exact selected
    child under those same locks on application; an intervening writer wins.
    """
    now = time.time() if now is None else now
    if min(age_days, max_bytes, grace_days) < 0:
        raise ValueError('Cache retention requires nonnegative age and budget.')
    candidates = []
    for spec in groups:
        options = {key: value for key, value in spec.items() if key not in {'last_used', 'ownership_files'}}
        for row in owned_entries(**options):
            path = Path(row['path'])
            try:
                stamp = spec.get('last_used', lambda p: p.stat().st_mtime)(path)
                if row['allocated_bytes'] is not None:
                    candidates.append((stamp, str(path), row['allocated_bytes'], spec, bool(row['protected'])))
            except OSError:
                continue
    remaining = sum(size for _, _, size, _, _ in candidates)
    selected_paths = []
    for stamp, name, size, spec, protected in sorted(candidates, key=lambda row: (row[0], row[1])):
        age = now - stamp
        if protected or age < grace_days * 86400 or age < age_days * 86400 and remaining <= max_bytes:
            continue
        options = dict(spec)
        eligible = options.pop('eligible')
        rows = prune(**options, eligible=lambda p, name=name, eligible=eligible: str(p) == name and eligible(p),
                     keep=0, age_days=0, grace_days=grace_days, now=now, apply=apply)
        if rows:
            remaining -= size
            selected_paths.extend(rows)
    return selected_paths


def owned_entries(root, *, eligible, lock_path=None, protection=None, ownership_files=()):
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
                    if (any(linked(part) for part in (path, *path.parents))
                            or not path.is_dir() or not eligible(path)):
                        continue
                    reason = protection_reason(path) or (protection(path) if protection else '')
            except RuntimeError:
                reason = 'In use by an active operation'
            try:
                size = allocated_bytes(path)
            except OSError:
                size = None
            rows.append(dict(name=path.name, path=str(path), protected=reason, allocated_bytes=size))
    return rows


def delete_owned(root, names, *, eligible, lock_path=None, protection=None, ownership_files=()):
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
                    if (any(linked(part) for part in (path, *path.parents))
                            or not path.is_dir() or not eligible(path)):
                        skipped.append(name + ': no longer an owned output')
                        continue
                    reason = protection_reason(path) or (protection(path) if protection else '')
                    if reason:
                        skipped.append(name + ': ' + reason)
                        continue
                    remove_tree(path, ownership_files=ownership_files)
                    removed.append(str(path))
            except (RuntimeError, OSError, ValueError) as error:
                skipped.append(name + ': ' + str(error))
    return dict(removed=removed, skipped=skipped)


# Compatibility names for project storage policies.
pinned = has_retention_protection
explicitly_pinned = has_keep_marker
