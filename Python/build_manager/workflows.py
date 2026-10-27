"""Durable step recovery and artifact-scoped, session-only effect review."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from commonUtils.runtime.streams import file_sha256
from commonUtils.runtime.operations import check_cancelled

EXTERNAL={'deploy','upload','publish','dispatch'}


def start_authorized_effects(plan):
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


def ancestors(plan,step):
    phases={phase.id:phase for phase in plan.phases};needed=set()
    def walk(name):
        for parent in phases[name].dependencies:
            if parent not in needed:needed.add(parent);walk(parent)
    walk(step);return needed


def review_identity(plan,step,rows,*,cancelled=lambda: False):
    needed=ancestors(plan,step)
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


def recover(plan,report,*,reconcile=None,cancelled=lambda: False):
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
                raise ValueError('Uncertain external operation requires reconciliation before retry: '+row['id'])
            receipt=reconcile(row['id'],row)
            if receipt.get('status') not in {'passed','not-performed'}:
                raise ValueError('Remote outcome remains unknown; no duplicate action was started.')
            row.update(status='passed' if receipt['status']=='passed' else 'interrupted',receipt=receipt)
        rows.append(row)
    return rows
