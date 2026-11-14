"""Inventory and explicitly delete evidence from declared project result folders."""
from contextlib import ExitStack
from pathlib import Path, PureWindowsPath
import os
import stat
import time

from .history import load_run
from .locking import workspace_lock
from .retention import linked, nested_workflow_hold_reason, protection_reason, remove_tree

BULKY_SUFFIXES = {'.apk', '.aab', '.ipa', '.log', '.jsonl', '.stderr',
                  '.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov'}
LOOSE_SUFFIXES = {'.log', '.jsonl', '.stderr', '.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov'}
MIN_LOOSE_AGE = 24 * 60 * 60


def evidence_root(project, value):
    path = Path(value)
    windows = PureWindowsPath(value)
    if (not path.parts or path.is_absolute() or windows.drive or windows.root
            or '..' in path.parts or '\x00' in value or '\\' in value or ':' in value):
        raise ValueError('Test evidence folders must be checkout-relative.')
    return project / path


def history_roots(project):
    primary = Path(project.results_directory).absolute()
    root = Path(getattr(project, 'root', primary.parent)).absolute()
    declared = getattr(project, 'descriptor', {}).get('legacy_results', [])
    roots = (primary, *(evidence_root(root, value) for value in declared))
    return tuple(dict.fromkeys(folder for folder in roots if folder != root
                              and folder.is_relative_to(root) and '..' not in folder.parts
                              and not any(linked(part) for part in (folder, *folder.parents))))


def result_roots(project):
    directory = getattr(project, 'results_directory', None)
    if directory is None:
        return {}
    primary = Path(directory).absolute()
    root = Path(getattr(project, 'root', primary.parent)).absolute()
    declared = getattr(project, 'descriptor', {}).get('test_evidence', [])
    extras = [evidence_root(root, value) for value in declared]
    return {folder: folder in extras for folder in (*history_roots(project), *extras)
            if folder != root and folder.is_relative_to(root)
            and '..' not in folder.parts
            and not any(linked(part) for part in (folder, *folder.parents))}


def size(info):
    return getattr(info, 'st_blocks', (info.st_size + 511) // 512) * 512


def stamp(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def fail(error):
    raise error


def run_files(path):
    """Return ordinary files within a run. Refuse embedded checkouts."""
    for directory, dirs, files in os.walk(path, onerror=fail):
        folder = Path(directory)
        if '.git' in dirs or '.git' in files:
            raise ValueError('Contains a source checkout')
        dirs[:] = [name for name in dirs if not linked(folder / name)]
        for name in files:
            file = folder / name
            info = file.lstat()
            if stat.S_ISREG(info.st_mode) and not linked(file):
                yield file, info


def run_state(path):
    records = [path / name for name in ('plan.json', 'result.json')]
    if any(linked(record) or not record.is_file() for record in records):
        raise ValueError('Run record is missing or linked')
    _, report = load_run(records[1])
    status = report['status']
    reason = ''
    if status in {'queued', 'running'}:
        reason = 'Run is active'
    elif status == 'unknown' or any(row['status'] == 'unknown' for row in report['phases']):
        reason = 'External outcome needs review'
    elif report.get('holds') or status == 'awaiting_review' and not report.get('retirement'):
        reason = 'Run is saved for review or continuation'
    else:
        reason = protection_reason(path) or nested_workflow_hold_reason(path)
    return status, reason, [stamp(record.lstat()) for record in records]


def inspect(path, kind):
    info = path.lstat()
    if linked(path):
        raise ValueError('Linked evidence')
    if kind == 'file':
        if not stat.S_ISREG(info.st_mode) or path.suffix.lower() not in LOOSE_SUFFIXES:
            raise ValueError('File is outside the declared evidence types')
        reason = ''
        if (path.parent / '.keep').exists() or path.with_name(path.name + '.keep').exists():
            reason = 'Pinned by .keep'
        elif time.time() - info.st_mtime < MIN_LOOSE_AGE:
            reason = 'Recently written'
        return 'Loose evidence', reason, size(info), size(info), stamp(info)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Run folder is missing')
    status, reason, version = run_state(path)
    total = bulky = 0
    for file, file_info in run_files(path):
        total += size(file_info)
        if file.suffix.lower() in BULKY_SUFFIXES:
            bulky += size(file_info)
    return status, reason, total, bulky, version


def inventory(project):
    rows = []
    for folder, loose in result_roots(project).items():
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.name.startswith('.') or linked(path):
                continue
            kind = 'run' if (path / 'result.json').is_file() else 'file'
            if kind == 'file' and (not loose or path.suffix.lower() not in LOOSE_SUFFIXES or not path.is_file()):
                continue
            try:
                status, reason, total, bulky, version = inspect(path, kind)
            except (OSError, ValueError) as error:
                status, reason, total, bulky, version = 'Unavailable', str(error), None, None, None
            modified = (version[1][-1] if kind == 'run' else version[-1]) / 1e9 if version else None
            rows.append(dict(path=str(path), name=path.name, kind=kind, status=status, protected=reason,
                             allocated_bytes=total, bulky_bytes=bulky, version=version, modified=modified))
    return rows


def delete(project, rows, *, entire=False):
    if hasattr(project, 'registry'):
        registered, descriptor = project.registry.resolve(project.key, trusted=True)
        if registered['root'] != str(project.root) or descriptor != project.descriptor:
            raise ValueError('Project registration changed. Reopen storage to review it.')
    result = dict(removed=[], skipped=[])
    roots = result_roots(project)
    for row in rows:
        path = Path(row['path'])
        kind = row['kind']
        try:
            if (path.parent not in roots or path.name.startswith('.') or kind not in {'run', 'file'}
                    or kind == 'file' and not roots[path.parent]):
                raise ValueError('Select a direct entry in a declared evidence folder')
            with ExitStack() as locks:
                if any(linked(part) for part in (path, *path.parents)):
                    raise ValueError('Linked evidence')
                if kind == 'run':
                    if not path.is_dir() or linked(path / 'supervisor.lock'):
                        raise ValueError('Run folder or lock is unavailable')
                    locks.enter_context(workspace_lock(path / 'supervisor.lock'))
                    locks.enter_context(workspace_lock(path.parent / ('.' + path.name + '.retention.lock')))
                _, reason, total, bulky, version = inspect(path, kind)
                expected_size = row['allocated_bytes'] if entire else row['bulky_bytes']
                if reason or version != row['version'] or (total if entire else bulky) != expected_size:
                    raise ValueError(reason or 'Evidence changed. Refresh and review the selection again')
                if kind == 'file':
                    if entire:
                        raise ValueError('Loose evidence uses Delete bulky files')
                    path.unlink()
                elif entire:
                    # Keep the supervisor lock in place for concurrent resume attempts and Windows.
                    # Keep the history records until bulky data has been removed.
                    for child in path.iterdir():
                        if child.name not in {'supervisor.lock', 'plan.json', 'result.json'}:
                            remove_tree(child)
                    (path / 'result.json').unlink()
                    (path / 'plan.json').unlink()
                else:
                    for file, _ in run_files(path):
                        if file.suffix.lower() in BULKY_SUFFIXES:
                            file.unlink()
            result['removed'].append(str(path))
        except (OSError, RuntimeError, ValueError) as error:
            result['skipped'].append(str(path) + ': ' + str(error))
    return result
