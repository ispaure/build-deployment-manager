"""Reviewed retirement releases a run's holds without rewriting its outcome."""
from datetime import datetime, timezone
from pathlib import Path

from .history import load_run, recent_runs
from .locking import workspace_lock
from .profiles import save_json
from .retention import release_workflow_hold, lease, linked


class RetiredRunError(ValueError):
    pass


def require_resumable(report):
    if report.get('retirement'):
        raise RetiredRunError('This workflow was retired; inspect its evidence or prepare a new run.')


def list_held_or_retired_runs(runs_directory):
    rows = recent_runs(runs_directory, limit=1000)
    return [row for row in rows if row.get('holds') or row.get('retired')]


def retire_run(runs_directory, run_name, *, confirmed=False):
    """Retain logs, receipts and unknown outcomes; prohibit further continuation.

    The retirement record precedes hold release so a crash can be retried safely.
    Only this run's owner key is removed, leaving other workflow holds intact.
    """
    if not confirmed:
        raise ValueError('Review the workflow and confirm retirement first.')
    if not isinstance(run_name, str) or run_name in {'', '.', '..'} or Path(run_name).name != run_name or '/' in run_name or '\\' in run_name:
        raise ValueError('Choose a direct saved run name.')
    runs_directory = Path(runs_directory).absolute()
    run_directory = runs_directory / run_name
    if any(linked(p) for p in (run_directory, *run_directory.parents)) or not run_directory.is_dir():
        raise ValueError('Retirement requires an existing unlinked project run.')
    if any(linked(run_directory / filename) for filename in ('plan.json', 'result.json')):
        raise ValueError('Retirement refuses linked run records.')
    with workspace_lock(run_directory / 'supervisor.lock'), lease(run_directory):
        plan, report = load_run(run_directory / 'result.json')
        if report['status'] in {'queued', 'running'}:
            raise ValueError('Stop or recover the recorded active workflow before retiring it.')
        allowed = {str(run_directory), str(Path(plan.workspace))}
        allowed.update(str(Path(value).parent) for phase in plan.phases for value in phase.artifacts)
        allowed.update(str(Path(value).with_suffix('')) for value in plan.resource_locks)
        holds = report.get('holds', [])
        if (not isinstance(holds, list) or any(not isinstance(p, str) or p not in allowed
                or not Path(p).is_absolute() or any(linked(q) for q in (Path(p), *Path(p).parents)) for p in holds)):
            raise ValueError('Saved holds disagree with the declared plan; preserve and inspect the record.')
        report.setdefault('retirement', dict(at=datetime.now(timezone.utc).isoformat(),
            reason='Superseded workflow; continuation disabled. External outcomes remain unchanged.'))
        save_json(run_directory / 'result.json', report)
        owner = str(run_directory.resolve())
        for path in holds:
            release_workflow_hold(path, owner)
        report['holds'] = []
        save_json(run_directory / 'result.json', report)
    return dict(name=run_name, status=report['status'], retired=True, released_holds=len(holds))
