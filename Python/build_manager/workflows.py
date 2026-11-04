"""Durable step recovery and artifact-scoped, session-only effect review."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from commonUtils.runtime.streams import file_sha256
from commonUtils.runtime.operations import check_cancelled

EXTERNAL={'deploy','upload','publish','dispatch'}


def require_build_only(plan):
    """Admit only artifact preparation and inspection for the explicit build goal."""
    effects = {phase.effect if phase.effect != 'inherit' else plan.effect for phase in plan.phases}
    if 'build' not in effects or effects - {'build', 'inspect'}:
        raise ValueError('Build only requires build steps and permits inspection only; tests and delivery actions are excluded.')


def apply_start_review_policy(plan):
    """Bind fresh GUI review to selected deliveries/hosted checks, never history."""
    from dataclasses import replace
    destinations = plan.journey.get('destinations', {})
    dispatches = {step for row in plan.journey.get('executions', {}).values()
                  if row.get('backend') == 'GitHub' for step in row.get('steps', [])}
    phases = []
    for phase in plan.phases:
        providers = {name for name, row in destinations.items() if phase.id in row['steps']}
        provider = phase.provider or (next(iter(providers)) if len(providers) == 1 else '')
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        if not provider and effect == 'dispatch' and phase.id in dispatches:
            provider = 'github'
        if (effect == 'upload' and provider in {'firebase', 'testflight'}
                or effect in {'upload', 'publish', 'dispatch'} and provider == 'github'):
            phase = replace(phase, effect=effect, provider=provider, approval_required=False)
        phases.append(phase)
    return replace(plan, phases=tuple(phases))


def verify_artifacts(row, *, cancelled=lambda: False):
    for artifact in row.get('artifacts',[]):
        check_cancelled(cancelled)
        path=Path(artifact['path'])
        original=Path(artifact.get('original_path',artifact['path']))
        if (not path.is_file() or not original.is_file()
                or file_sha256(path, cancelled=cancelled)!=artifact['sha256']
                or file_sha256(original, cancelled=cancelled)!=artifact['sha256']):
            raise ValueError('Retained artifact is missing or changed; inspect a new preparation: '+str(path))


def transitive_dependency_ids(plan, phase_id):
    """Follow success dependencies, excluding completion-only waits_for edges."""
    phases = {phase.id: phase for phase in plan.phases}
    needed = set()

    def walk(current_id):
        for parent_id in phases[current_id].dependencies:
            if parent_id not in needed:
                needed.add(parent_id)
                walk(parent_id)

    walk(phase_id)
    return needed


def review_identity(plan,step,rows,*,cancelled=lambda: False):
    needed=transitive_dependency_ids(plan,step)
    selected={row['id']:row for row in rows if row['id'] in needed}
    if any(name not in selected or selected[name]['status']!='passed' for name in needed):
        raise ValueError('Required workflow gates have not passed; no effect can be approved.')
    for row in selected.values():verify_artifacts(row, cancelled=cancelled)
    payload=dict(plan=plan.identity,step=step,artifacts=[a for row in selected.values() for a in row.get('artifacts',[])])
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Approval:
    step: str
    identity: str


def approve(plan,step,report,*,cancelled=lambda: False):
    if report['plan_identity']!=plan.identity:raise ValueError('Review belongs to different source/settings.')
    return Approval(step,review_identity(plan,step,report['phases'],cancelled=cancelled))


def recover_phase_records(plan,report,*,reconcile=None,cancelled=lambda: False,preserve_unknown=False):
    from .run_retirement import require_resumable
    require_resumable(report)
    if report.get('schema')!=1 or report.get('plan_identity')!=plan.identity:
        raise ValueError('Result schema or plan identity changed; preserve the original run.')
    effects={phase.id:phase.effect if phase.effect!='inherit' else plan.effect for phase in plan.phases}
    rows=[]
    for original in report['phases']:
        check_cancelled(cancelled)
        row=dict(original)
        if row['status']=='running':
            row['status']='unknown' if effects[row['id']] in EXTERNAL else 'interrupted'
        if row['status']=='passed':verify_artifacts(row,cancelled=cancelled)
        if row['status']=='unknown':
            if reconcile is None:
                if preserve_unknown:
                    rows.append(row)
                    continue  # Retain the intent; never schedule it or its consumers.
                raise ValueError('Uncertain external operation requires reconciliation before retry: '+row['id'])
            receipt=reconcile(row['id'],row)
            if receipt.get('status') not in {'passed','not-performed'}:
                raise ValueError('Remote outcome remains unknown; no duplicate action was started.')
            row.update(status='passed' if receipt['status']=='passed' else 'interrupted',receipt=receipt)
        rows.append(row)
    return rows


def retained_phase_records(plan, previous, *, retry_failed=True):
    """Retain evidence only while its nonexternal prerequisites remain retained.

    Cleanup is attempt-bound: a prior no-op cannot order a newly retried owner.
    Completed/unknown external effects remain immutable and are never replayed.
    """
    statuses = {'passed', 'unknown'}
    if not retry_failed:
        statuses.update({'failed', 'skipped', 'cancelled', 'timeout', 'interrupted'})
    rows = {row['id']: row for row in previous if row['status'] in statuses}
    pending = {phase.id for phase in plan.phases if phase.id not in rows}
    changed = True
    while changed:
        changed = False
        for phase in plan.phases:
            row = rows.get(phase.id)
            effect = phase.effect if phase.effect != 'inherit' else plan.effect
            if row is None:
                continue
            prerequisites = (*phase.dependencies, *phase.waits_for)
            stale = (any(name in pending for name in prerequisites)
                     or phase.always and not prerequisites and bool(pending))
            if effect in EXTERNAL:
                if phase.always and stale and row['status'] in {'passed', 'unknown'}:
                    raise ValueError('External cleanup cannot be automatically repeated or reused for a retried owner: '
                                     + phase.id + '. Review its outcome and prepare a separately reviewed workflow.')
                continue
            if row['status'] == 'passed' and stale:
                del rows[phase.id]
                pending.add(phase.id)
                changed = True
    return rows
