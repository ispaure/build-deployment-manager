"""Headless storage review for adapter declarations and manager-owned evidence."""
from collections import defaultdict
from contextlib import nullcontext
import os
from pathlib import Path
import sqlite3
import stat
from time import monotonic

from commonUtils.filesystem.index import DirectoryCache
from commonUtils.filesystem.index.allocation import allocated_size
from commonUtils.filesystem.native_paths import native_path
from commonUtils.runtime.operations import check_cancelled

from .adapter_sdk import supports
from .run_retirement import list_held_or_retired_runs
from .test_storage import inventory as evidence_inventory, result_roots


BUILDS = 'Builds and working files'
CACHES = 'Rebuildable caches'
SAVED_RUNS = 'Saved runs and test results'
CATEGORIES = (BUILDS, CACHES, SAVED_RUNS)


def read_owned_inventory(project, *, cancelled=lambda: False,
                         report=lambda done, total, message: None):
    """Read declarations and existing eligibility reasons through their owners."""
    check_cancelled(cancelled)
    report(0, 0, 'Reading owned build files…')
    outputs = ()
    if supports(project, 'storage_inventory'):
        request = project.with_cancellation(cancelled) if hasattr(project, 'with_cancellation') else project
        check_cancelled(cancelled)
        try:
            outputs = tuple(request.storage_inventory())
        except Exception:
            check_cancelled(cancelled)
            raise
    check_cancelled(cancelled)
    report(0, 0, 'Reading saved runs and test results…')
    evidence = tuple(evidence_inventory(project))
    check_cancelled(cancelled)
    workflows = []
    for folder in result_roots(project):
        check_cancelled(cancelled)
        workflows.extend(list_held_or_retired_runs(folder))
    check_cancelled(cancelled)
    return outputs, evidence, tuple(workflows)


def _path_key(path):
    return os.path.normcase(str(path))


def _category(source, row):
    if source == 'evidence':
        return SAVED_RUNS
    # Classify descriptions provided by the owner. Location and file names alone
    # convey no policy. Use the part before a platform/owner qualifier.
    for field in ('category', 'group', 'label'):
        description = str(row.get(field) or '').split(' / ', 1)[0].strip().casefold()
        if description in {'cache', 'caches', 'build cache', 'build caches',
                           'rebuildable cache', 'rebuildable caches'}:
            return CACHES
        if description.endswith((' build caches', ' compiler caches', ' project caches')):
            return CACHES
    return BUILDS


def _bytes(value):
    return value if type(value) is int and value >= 0 else None


def _file_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def _inode(info):
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _path_stats(path, ancestors):
    """Read an unlinked chain from the filesystem root down, without resolving aliases."""
    for part in reversed(path.parents):
        if part not in ancestors:
            ancestors[part] = _unlinked_stat(part, directory=True)
        if isinstance(ancestors[part], str):
            return ancestors[part]
    return _unlinked_stat(path)


def _reparse_link(info):
    tag = getattr(info, 'st_reparse_tag', 0)
    return tag in (getattr(stat, 'IO_REPARSE_TAG_MOUNT_POINT', -1),
                   getattr(stat, 'IO_REPARSE_TAG_SYMLINK', -1))


def _unlinked_stat(path, *, directory=False):
    try:
        info = native_path(path).lstat()
    except (OSError, ValueError):
        return 'Location is missing or inaccessible'
    if stat.S_ISLNK(info.st_mode) or _reparse_link(info):
        return 'Location or an enclosing folder is linked'
    if not (stat.S_ISDIR(info.st_mode) or not directory and stat.S_ISREG(info.st_mode)):
        return 'Location is outside ordinary file and directory storage'
    return info


def _action_key(source, row):
    if source == 'output':
        return source, str(row.get('group') or ''), str(row.get('name') or '')
    return source, row.get('kind')


def _add_reason(row, reason):
    row['protected'] = ' · '.join(dict.fromkeys(filter(None, (row['protected'], reason))))


def _declarations(outputs, evidence, cancelled):
    """Merge declared paths and build containment edges before any directory scan."""
    rows, aliases, ancestors, actions = {}, {}, {}, defaultdict(set)
    for source, declarations in (('output', outputs), ('evidence', evidence)):
        for action in sorted(declarations, key=lambda row: str(row.get('path') or '')):
            check_cancelled(cancelled)
            original = str(action.get('path') or '')
            path = Path(original)
            valid = path.is_absolute() and path != Path(path.anchor) and '..' not in path.parts
            key = _path_key(path) if valid else original
            info = _path_stats(path, ancestors) if valid else 'Location must be an absolute owned path'
            reason = str(action.get('protected') or '')
            identity = kind = inode = None
            if isinstance(info, str):
                reason = ' · '.join(dict.fromkeys(filter(None, (reason, info))))
            else:
                identity = _file_identity(info)
                kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file'
                # Allocation is by file path, so different hard-link names are
                # independent. Same-inode directories identify spelling/mount aliases.
                inode = _inode(info) if kind == 'directory' or info.st_nlink == 1 else None
            category = _category(source, action)
            if inode is not None:
                key = aliases.setdefault(inode, key)
            action_key = _action_key(source, action)
            if source == 'output':
                actions[action_key].add(key)
                if not all(action_key[1:]):
                    reason = ' · '.join(filter(None, (reason, 'Adapter cleanup identity is missing')))
            if key in rows:
                previous = rows[key]
                if (previous['category'] != category or previous['identity'] != identity
                        or _action_key(*previous['owners'][0]) != action_key
                        or previous['action'].get('allocated_bytes') != action.get('allocated_bytes')
                        or previous['action'].get('version') != action.get('version')
                        or previous['protected'] != reason):
                    previous['shared'] = True
                    _add_reason(previous, 'Location has conflicting storage declarations')
                    if reason:
                        _add_reason(previous, reason)
                if identity != previous['identity']:
                    _unavailable(previous, 'Location changed during storage review')
                previous['owners'].append((source, action))
                previous['paths'].append(path)
                continue
            value = _bytes(action.get('allocated_bytes')) if identity else None
            logical = None
            measurement = 'reported' if value is not None else 'unknown'
            if source == 'evidence' and kind == 'file':
                value = _bytes(allocated_size(native_path(path), info))
                logical, measurement = info.st_size, 'file'
            rows[key] = dict(key=key, path=str(path) if valid else original, source=source, action=action,
                             owners=[(source, action)], paths=[path], category=category,
                             label=action.get('label') or action.get('name') or path.name,
                             group=action.get('category') or action.get('group') or '',
                             status=action.get('status') or '', protected=reason, identity=identity, kind=kind,
                             shared=False, parent_key=None, child_keys=[], protected_descendant='',
                             contains_protected=False, allocated_bytes=value, logical_bytes=logical,
                             bulky_bytes=_bytes(action.get('bulky_bytes')) if source == 'evidence' else None,
                             measurement=measurement, partial=value is None, stale=False, scanned_at=None)
    for keys in actions.values():
        if len(keys) > 1:
            for key in keys:
                rows[key]['shared'] = True
                _add_reason(rows[key], 'Adapter cleanup identity refers to multiple locations')
    for key, row in rows.items():
        check_cancelled(cancelled)
        for path in row.pop('paths'):
            for parent in path.parents:
                owner = _path_key(parent)
                if owner not in rows and parent in ancestors and not isinstance(ancestors[parent], str):
                    owner = aliases.get(_inode(ancestors[parent]))
                if owner in rows and owner != key:
                    row['parent_key'] = owner
                    rows[owner]['child_keys'].append(key)
                    break
            if row['parent_key'] is not None:
                break
        row['owners'] = tuple(row['owners'])
    return rows


def _subtrees(rows, cancelled):
    """Yield each independent root with its declared descendants, parent first."""
    seen = set()
    for root in rows.values():
        if root['parent_key'] is not None:
            continue
        stack, scope = [root], []
        while stack:
            check_cancelled(cancelled)
            row = stack.pop()
            seen.add(row['key'])
            scope.append(row)
            stack.extend(rows[key] for key in reversed(row['child_keys']))
        yield scope
    # An unusual mount alias may make ancestry cyclic. Preserve the declarations
    # for inspection and withhold those measurements and actions.
    for key in rows.keys() - seen:
        check_cancelled(cancelled)
        row = rows[key]
        _unavailable(row, 'Storage aliases have conflicting containment')
        row.update(parent_key=None, child_keys=[])
        yield [row]


def _finish(rows, scopes, workflows, scan_roots, issues, cancelled):
    category_totals = {category: dict(allocated_bytes=None, partial=False, stale=False,
                                      estimated=False, row_count=0, reviewable_bytes=0,
                                      reviewable_unknown=0) for category in CATEGORIES}
    for scope in scopes:
        for row in reversed(scope):
            check_cancelled(cancelled)
            children = [rows[key] for key in row['child_keys']]
            for child in children:
                if child['source'] != row['source'] or child['protected'] or child['protected_descendant']:
                    row['protected_descendant'] = 'Contains separately owned or protected storage'
                    break
            row['contains_protected'] = bool(row['protected_descendant'])
            value = row['allocated_bytes']
            partial, stale = row['partial'], row['stale']
            estimated = row['measurement'] == 'reported'
            if children:
                # Subtract complete immediate child footprints only. If coverage
                # is uncertain, keep the independently known child amounts and
                # leave the enclosing remainder unassigned.
                comparable = all(
                    child['allocated_bytes'] is not None and not child['partial']
                    and child['stale'] == stale
                    and (child['measurement'] == row['measurement'] or
                         not estimated and child['measurement'] == 'file')
                    for child in children
                )
                nested = sum(child['allocated_bytes'] for child in children) if comparable else None
                if value is None or nested is None or nested > value:
                    value, partial = None, True
                else:
                    value -= nested
            row['accounted_bytes'], row['accounting_partial'] = value, partial
            row['child_keys'] = tuple(row['child_keys'])
            totals = category_totals[row['category']]
            totals['row_count'] += 1
            if value is not None:
                totals['allocated_bytes'] = (totals['allocated_bytes'] or 0) + value
                totals['estimated'] |= estimated
            totals['partial'] |= partial
            totals['stale'] |= stale
        covered = set()
        for row in scope:
            if row['parent_key'] in covered:
                covered.add(row['key'])
                continue
            if row['protected'] or row['protected_descendant'] or not row['identity']:
                continue
            amount = row['bulky_bytes'] if row['source'] == 'evidence' else row['allocated_bytes']
            totals = category_totals[row['category']]
            if amount is None:
                totals['reviewable_unknown'] += 1
            else:
                totals['reviewable_bytes'] += amount
                covered.add(row['key'])
    for totals in category_totals.values():
        if not totals['row_count']:
            totals['allocated_bytes'] = 0
    known = [totals['allocated_bytes'] for totals in category_totals.values()
             if totals['row_count'] and totals['allocated_bytes'] is not None]
    ordered = tuple(sorted(rows.values(), key=lambda row: (
        row['allocated_bytes'] is None, -(row['allocated_bytes'] or 0), row['key'])))
    return dict(rows=ordered, by_key=rows, workflows=workflows, categories=category_totals,
                allocated_bytes=sum(known) if known or not rows else None,
                partial=any(value['partial'] for value in category_totals.values()),
                stale=any(value['stale'] for value in category_totals.values()),
                estimated=any(value['estimated'] for value in category_totals.values()),
                reviewable_bytes=sum(value['reviewable_bytes'] for value in category_totals.values()),
                reviewable_unknown=sum(value['reviewable_unknown'] for value in category_totals.values()),
                chart=tuple((category, totals['allocated_bytes']) for category, totals in category_totals.items()
                            if totals['allocated_bytes']),
                scan_roots=scan_roots, issues=tuple(issues))


def normalize(outputs, evidence=(), workflows=(), *, cancelled=lambda: False):
    """Normalize current declarations without reading or writing the directory index."""
    rows = _declarations(outputs, evidence, cancelled)
    scopes = tuple(_subtrees(rows, cancelled))
    roots = tuple(Path(group[0]['path']) for group in _scan_groups(scopes, cancelled))
    return _finish(rows, scopes, tuple(workflows), roots, (), cancelled)


def _scan_groups(scopes, cancelled):
    """Group explicit directories and their descendants under a single scan."""
    groups = {}
    for scope in scopes:
        covering = {}
        for row in scope:
            check_cancelled(cancelled)
            root = covering.get(row['parent_key'])
            if root is None:
                if row['kind'] == 'directory':
                    covering[row['key']] = row['key']
                    groups[row['key']] = [row]
            else:
                covering[row['key']] = root
                if row['identity'] is not None:
                    groups[root].append(row)
    return tuple(groups.values())


def _current_scope(row):
    return _path_stats(Path(row['path']), {})


def _unavailable(row, reason):
    row.update(allocated_bytes=None, logical_bytes=None, measurement='unknown', partial=True,
               stale=False, scanned_at=None, identity=None, kind=None)
    _add_reason(row, reason)


def _read_index(cache, group, *, cached, cancelled, report, issues):
    root = group[0]
    path = Path(root['path'])
    last_check = last_report = 0.0

    def check_scope(force=False):
        nonlocal last_check
        if force or monotonic() - last_check >= .05:
            last_check = monotonic()
            info = _current_scope(root)
            if isinstance(info, str) or _file_identity(info)[:3] != root['identity'][:3]:
                raise OSError('Index scope was replaced or linked')

    def scan_cancelled():
        if cancelled():
            return True
        check_scope()
        return False

    def scan_report(done, total, message):
        nonlocal last_report
        if monotonic() - last_report >= .08:
            last_report = monotonic()
            report(done, total, message)
            check_cancelled(cancelled)
            check_scope(force=True)

    check_cancelled(cancelled)
    try:
        check_scope(force=True)
        snapshot = (cache.peek(path, cancelled=scan_cancelled) if cached else
                    cache.get(path, cancelled=scan_cancelled, report=scan_report))
        if snapshot is None:
            return
        with snapshot:
            values = {}
            # Keep bounded SQLite parameter sets even for deeply grouped workspaces.
            for offset in range(0, len(group), 500):
                paths = [Path(row['path']) for row in group[offset:offset + 500] if row['kind'] == 'directory']
                values.update(snapshot.folder_stats(paths, cancelled=scan_cancelled))
            check_scope(force=True)
            ancestors = {}
            for row in group:
                check_cancelled(cancelled)
                row_path = Path(row['path'])
                info = _path_stats(row_path, ancestors)
                if isinstance(info, str) or _file_identity(info) != row['identity']:
                    _unavailable(row, 'Location changed during storage review')
                elif (stats := values.get(row_path)) is not None:
                    incomplete = not stats.complete or row is root and not snapshot.complete
                    known_allocation = stats.files > stats.disk_unknown or not (incomplete or stats.disk_unknown)
                    disk = stats.disk_size if known_allocation else None
                    row.update(allocated_bytes=disk, logical_bytes=stats.size, measurement='indexed',
                               partial=incomplete or bool(stats.disk_unknown),
                               stale=cached or stats.stale, scanned_at=stats.scanned_at or snapshot.scanned_at)
                elif not cached and row['kind'] == 'directory':
                    row['partial'] = True
            if not cached and not snapshot.complete:
                issues.append(f'{path}: Index refresh is incomplete.')
                for row in group:
                    row['scan_issue'] = 'Index refresh is incomplete; some files could not be measured.'
    except (OSError, sqlite3.Error, ValueError) as error:
        check_cancelled(cancelled)
        issues.append(f'{path}: {error}')
        if not cached:
            for row in group:
                info = _current_scope(row)
                if isinstance(info, str) or _file_identity(info) != row['identity']:
                    _unavailable(row, 'Location changed during storage review')
                else:
                    row['partial'] = True
                row['scan_issue'] = str(error)


def gather(project, *, cache=None, cancelled=lambda: False,
           report=lambda done, total, message: None, publish_cached=None, measure=True):
    """Run on a worker. Publish cached measurements before refreshing owned scopes."""
    outputs, evidence, workflows = read_owned_inventory(project, cancelled=cancelled, report=report)
    if not measure:
        return normalize(outputs, evidence, workflows, cancelled=cancelled)
    rows = _declarations(outputs, evidence, cancelled)
    scopes = tuple(_subtrees(rows, cancelled))
    groups = _scan_groups(scopes, cancelled)
    roots = tuple(Path(group[0]['path']) for group in groups)
    issues = []
    with DirectoryCache() if cache is None else nullcontext(cache) as owned_cache:
        if publish_cached is not None:
            report(0, len(groups), 'Reading saved size measurements…')
            cached_rows = {key: dict(row) for key, row in rows.items()}
            for group in groups:
                _read_index(owned_cache, [cached_rows[row['key']] for row in group], cached=True,
                            cancelled=cancelled, report=report, issues=issues)
            _revalidate(cached_rows, cancelled)
            publish_cached(_finish(cached_rows, tuple(_subtrees(cached_rows, cancelled)), workflows,
                                   roots, issues, cancelled))
        for index, group in enumerate(groups, 1):
            check_cancelled(cancelled)
            report(index - 1, len(groups), f'Checking storage scope {index} of {len(groups)}…')
            _read_index(owned_cache, group, cached=False, cancelled=cancelled, report=report, issues=issues)
    _revalidate(rows, cancelled)
    return _finish(rows, scopes, workflows, roots, issues, cancelled)


def _revalidate(rows, cancelled):
    """Recheck scope identities before publishing any measurements or action candidates."""
    check_cancelled(cancelled)
    ancestors = {}
    for row in rows.values():
        check_cancelled(cancelled)
        if row['identity'] is not None:
            info = _path_stats(Path(row['path']), ancestors)
            if isinstance(info, str) or _file_identity(info) != row['identity']:
                _unavailable(row, 'Location changed during storage review')


def invalidate(cache, snapshot, paths=()):
    """Mark index scopes touched by a mutation for revalidation on their next read."""
    paths = tuple(Path(path) for path in paths)
    affected = set(paths)
    for root in snapshot['scan_roots']:
        if not paths or any(path == root or path in root.parents or root in path.parents for path in paths):
            affected.add(root)
    for path in affected:
        cache.invalidate(path)
