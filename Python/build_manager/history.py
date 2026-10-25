"""Read-only bounded project-owned run discovery; never executes retained plans."""
import json
import math
from pathlib import Path

from .models import Plan

MAX_RESULT_BYTES = 32 * 1024 * 1024
STATUSES = {'queued', 'running', 'passed', 'failed', 'cancelled', 'awaiting_review', 'unknown'}


def valid_seconds(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def read_report(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError('Result report is too large.')
    try:
        report = json.loads(raw)
    except RecursionError as error:
        raise ValueError('Result report is nested too deeply.') from error
    if (not isinstance(report, dict) or report.get('schema') != 1
            or not isinstance(report.get('status'), str) or report['status'] not in STATUSES
            or not isinstance(report.get('phases'), list)):
        raise ValueError('Invalid result report.')
    seconds = report.get('seconds')
    if seconds is not None and not valid_seconds(seconds):
        raise ValueError('Invalid run duration.')
    for row in report['phases']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('status'), str):
            raise ValueError('Invalid result step.')
        if row.get('seconds') is not None and not valid_seconds(row['seconds']):
            raise ValueError('Invalid step duration.')
        if not isinstance(row.get('tests', []), list) or not isinstance(row.get('artifacts', []), list):
            raise ValueError('Invalid step evidence.')
        for case in row.get('tests', []):
            if (not isinstance(case, dict) or any(not isinstance(case.get(key), str)
                    for key in ('name', 'classname', 'suite', 'message'))
                    or not isinstance(case.get('status'), str) or case['status'] not in {'passed', 'failed', 'error', 'skipped'}
                    or case.get('seconds') is not None and not valid_seconds(case['seconds'])):
                raise ValueError('Invalid test case.')
        for artifact in row.get('artifacts', []):
            if not isinstance(artifact, dict) or any(not isinstance(artifact.get(key), str) for key in ('path', 'sha256')):
                raise ValueError('Invalid artifact evidence.')
    return report


def recent_runs(directory, limit=100):
    root = Path(directory)
    if not root.is_dir():
        return []
    rows = []
    # One level only: no snapshot/build/cache traversal and no adapter invocation.
    try:
        paths = sorted((path for path in root.glob('*/result.json') if not path.parent.is_symlink() and not path.is_symlink()),
                       key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return []
    for path in paths:
        try:
            report = read_report(path)
            rows.append(dict(path=str(path), started_at=str(report.get('started_at', '')),
                             operation=str(report.get('operation', '')), status=report['status'],
                             seconds=report.get('seconds')))
        except (OSError, ValueError):
            rows.append(dict(path=str(path), status='unreadable', operation=path.parent.name))
    return rows


def load_run(path):
    path = Path(path)
    report = read_report(path)
    plan = Plan.load(path.parent / 'plan.json')
    if report.get('plan_identity') != plan.identity:
        raise ValueError('Retained plan and result identity disagree.')
    names = [row['id'] for row in report['phases']]
    if len(names) != len(set(names)) or set(names) - {phase.id for phase in plan.phases}:
        raise ValueError('Retained result steps disagree with the plan.')
    return plan, report
