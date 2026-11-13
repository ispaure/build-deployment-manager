"""Reviewed cleanup orchestration; existing project owners authorize each removal.

Index values estimate space only. These helpers run on a worker and never import Qt
or a project implementation. Cancellation drains an admitted action before stopping.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from commonUtils.runtime.operations import OperationCancelled

from .adapter_sdk import supports
from .retention import linked


@dataclass(frozen=True)
class CleanupPreview:
    project_identity: str
    action: str
    rows: tuple
    skipped: tuple
    estimated_bytes: int
    unknown_count: int
    stale: bool
    consequence: str
    measurement_summary: str


CONSEQUENCES = {
    'outputs': ('Selected build files will be removed. Preparing again may take time. '
                'A retry or delivery that needs these exact files may no longer work. '
                'Published releases and installed apps are unchanged.'),
    'bulky': ('Logs, screenshots, recordings and copied installers will be removed. '
              'Run outcomes, structured reports and receipts remain in local history. '
              'Removed diagnosis evidence cannot be opened again; a retry or delivery '
              'may need its files prepared again.'),
    'runs': ('The selected runs will disappear from local history, including their '
             'reports, receipts and files. Their saved results cannot be inspected or '
             'continued afterward. Published releases are unchanged.'),
    'retire': ('These workflows cannot continue afterward. Only their storage holds '
               'are released. Logs, receipts and recorded outcomes remain; an unknown '
               'delivery outcome still needs checking with its provider.'),
}


def project_identity(project):
    """Validate current registration, then capture the scope without writing it."""
    root = str(getattr(project, 'root', Path(getattr(project, 'results_directory', '.')).parent))
    descriptor = getattr(project, 'descriptor', {})
    if hasattr(project, 'registry'):
        row, current = project.registry.resolve(project.key, trusted=True)
        if row['root'] != root or current != descriptor:
            raise ValueError('Project registration changed. Reopen storage to review it.')
    return json.dumps((getattr(project, 'key', None), root, descriptor,
                       str(getattr(project, 'results_directory', ''))), sort_keys=True, default=str)


def _token(row):
    action = row['action']
    fields = ('path', 'group', 'name', 'kind', 'version', 'allocated_bytes', 'bulky_bytes')
    return (row['source'], row['identity'],
            json.dumps({key: action.get(key) for key in fields}, sort_keys=True, default=str))


def unavailable(row, action):
    """Presentation exclusions supplement, and never replace, live owner guards."""
    if row.get('protected'):
        return row['protected']
    if row.get('protected_descendant'):
        return row['protected_descendant']
    if not row.get('identity'):
        return 'Location is unavailable. Refresh before reviewing cleanup.'
    if action == 'outputs' and row['source'] != 'output':
        return 'Use the separate saved-run cleanup actions.'
    if action in {'bulky', 'runs'} and row['source'] != 'evidence':
        return 'Use the build-file cleanup action.'
    if action == 'runs' and row['action'].get('kind') != 'run':
        return 'Loose evidence uses Remove bulky files.'
    if action == 'bulky' and not row['action'].get('bulky_bytes'):
        return 'No measured bulky files to remove.'
    return ''


def _current(project, cancelled, report):
    from .storage_inventory import normalize, read_owned_inventory
    outputs, evidence, workflows = read_owned_inventory(project, cancelled=cancelled, report=report)
    return normalize(outputs, evidence, workflows, cancelled=cancelled)


def _reviewed_rows(selected, current, action):
    accepted, skipped = [], []
    for previous in selected:
        row = current['by_key'].get(previous['key'])
        reason = (unavailable(row, action) if row is not None else 'No longer in this project inventory.')
        if not reason and _token(previous) != _token(row):
            reason = 'Files or ownership changed. Refresh and review again.'
        if reason:
            skipped.append(previous.get('label', previous['path']) + ': ' + reason)
        else:
            accepted.append(row)
    # Select an ancestor once, not that ancestor and its nested action again.
    ordered = []
    for row in accepted:
        ancestors, parent = set(), row.get('parent_key')
        while parent is not None and parent not in ancestors:
            ancestors.add(parent)
            parent = current['by_key'][parent].get('parent_key')
        ordered.append((len(ancestors), row['key'], row, ancestors))
    chosen = {}
    for _, _, row, ancestors in sorted(ordered, key=lambda entry: entry[:2]):
        if row['key'] in chosen or any(parent in chosen for parent in ancestors):
            continue
        chosen[row['key']] = row
    return tuple(chosen.values()), tuple(skipped)


def prepare_preview(project, selected, action, *, cancelled=lambda: False,
                    report=lambda done, total, message: None):
    """Refresh eligibility before the user sees and confirms a concrete preview."""
    if action not in {'outputs', 'bulky', 'runs'}:
        raise ValueError('Choose a supported cleanup action.')
    identity = project_identity(project)
    if action == 'outputs' and not supports(project, 'delete_storage'):
        raise ValueError('This project does not provide build-file cleanup.')
    current = _current(project, cancelled, report)
    rows, skipped = _reviewed_rows(selected, current, action)
    if project_identity(project) != identity:
        raise ValueError('Project changed while reviewing storage. Reopen it.')
    known = unknown = 0
    displayed = []
    for row in rows:
        original = next(item for item in selected if item['key'] == row['key'])
        displayed.append(dict(row, **{key: original.get(key) for key in
                         ('allocated_bytes', 'logical_bytes', 'partial', 'stale', 'measurement', 'scanned_at')}))
        value = row['action'].get('bulky_bytes') if action == 'bulky' else original.get('allocated_bytes')
        if value is None:
            unknown += 1
        else:
            known += value
        if original.get('partial') and value is not None:
            unknown += 1
    stale = any(row.get('stale') for row in displayed)
    reported = any(row.get('measurement') == 'reported' for row in displayed)
    measurement = ('Cached sizes may be stale' if stale else
                   'Includes project-reported estimates' if reported else 'Sizes measured during this scan')
    if unknown:
        measurement += f'; {unknown} incomplete sizes'
    consequence = CONSEQUENCES[action]
    if action == 'outputs':
        from .storage_inventory import CACHES
        if rows and all(row['category'] == CACHES for row in rows):
            consequence = ('Only the selected rebuildable cache folders will be removed. '
                           'Rebuilding their contents takes time; exact reproduction is not guaranteed. '
                           'Their containing builds and saved-run records remain.')
    consequence += ' Unselected locations outside the selected folders and protected data remain.'
    return CleanupPreview(identity, action, deepcopy(tuple(displayed)), skipped, known, unknown,
                          stale, consequence, measurement)


def execute(project, preview, *, cancelled=lambda: False,
            report=lambda done, total, message: None):
    """Revalidate the whole plan, then drain each existing guarded owner action.

    Group/name API-1 selection is not an atomic preview-inode token. Project
    owners retain their execution-time checks and no new authority is inferred.
    """
    result = dict(removed=[], skipped=list(preview.skipped), failed=[], cancelled=False)
    if cancelled():
        result['cancelled'] = True
        return result
    if project_identity(project) != preview.project_identity:
        raise ValueError('Project changed after preview. Reopen storage to review it.')
    try:
        current = _current(project, cancelled, report)
    except OperationCancelled:
        result['cancelled'] = True
        return result
    rows, changed = _reviewed_rows(preview.rows, current, preview.action)
    # A stale plan does not quietly change its destructive membership.
    if changed:
        result['skipped'].extend(changed)
        result['skipped'].extend(row['label'] + ': Nothing removed because the preview changed.' for row in rows)
        return result
    for index, row in enumerate(rows):
        if cancelled():
            result['cancelled'] = True
            result['skipped'].extend(item['label'] + ': Stopped before removal.' for item in rows[index:])
            break
        try:
            if project_identity(project) != preview.project_identity:
                raise ValueError('Project changed after preview. Reopen storage to review it.')
            # Re-read each remaining item after earlier actions: a new shared
            # declaration or protection can appear while the first item runs.
            if index:
                fresh = _current(project, cancelled, report)
                eligible, changed = _reviewed_rows((row,), fresh, preview.action)
                if changed:
                    result['skipped'].extend(changed)
                    continue
                row, = eligible
            report(index, len(rows), 'Removing ' + row['label'])
            if cancelled():
                result['cancelled'] = True
                result['skipped'].extend(item['label'] + ': Stopped before removal.' for item in rows[index:])
                break
            action = row['action']
            if preview.action == 'outputs':
                outcome = project.delete_storage({action['group']: [action['name']]})
            else:
                from .test_storage import delete
                outcome = delete(project, [action], entire=preview.action == 'runs')
            result['removed'].extend(outcome['removed'])
            result['skipped'].extend(outcome['skipped'])
        except OperationCancelled:
            result['cancelled'] = True
            result['skipped'].extend(item['label'] + ': Stopped before removal.' for item in rows[index:])
            break
        except (OSError, ValueError, RuntimeError) as error:
            result['failed'].append(row['label'] + ': ' + str(error))
    result['cancelled'] = result['cancelled'] or cancelled()
    report(len(result['removed']), len(rows), 'Cleanup finished' if not result['cancelled'] else 'Cleanup stopped')
    return result


def retire(project, rows, *, expected_project, cancelled=lambda: False,
           report=lambda done, total, message: None):
    """Retire only reviewed direct saved runs, using the existing owner locks."""
    from .run_retirement import retire_run
    from .test_storage import result_roots
    result = dict(retired=[], removed=[], skipped=[], failed=[], cancelled=False)
    for index, row in enumerate(rows):
        if cancelled():
            result['cancelled'] = True
            break
        try:
            if project_identity(project) != expected_project:
                raise ValueError('Project changed. Reopen storage before retiring workflows.')
            run = Path(row['path']).parent
            if run.parent not in result_roots(project) or any(linked(p) for p in (run, *run.parents)):
                raise ValueError('Run storage changed. Refresh before retiring.')
            report(index, len(rows), 'Retiring ' + run.name)
            if cancelled():
                result['cancelled'] = True
                break
            result['retired'].append(retire_run(run.parent, run.name, confirmed=True))
        except (OSError, ValueError, RuntimeError) as error:
            result['skipped'].append(row['path'] + ': ' + str(error))
    return result
