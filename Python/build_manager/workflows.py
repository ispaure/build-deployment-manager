"""Durable step recovery and artifact-scoped, session-only effect review."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

EXTERNAL={'deploy','upload','publish'}


def verify_artifacts(row):
    for artifact in row.get('artifacts',[]):
        path=Path(artifact['path'])
        original=Path(artifact.get('original_path',artifact['path']))
        if (not path.is_file() or not original.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']
                or hashlib.sha256(original.read_bytes()).hexdigest()!=artifact['sha256']):
            raise ValueError('Retained artifact is missing or changed; inspect a new preparation: '+str(path))


def ancestors(plan,step):
    phases={phase.id:phase for phase in plan.phases};needed=set()
    def walk(name):
        for parent in phases[name].dependencies:
            if parent not in needed:needed.add(parent);walk(parent)
    walk(step);return needed


def review_identity(plan,step,rows):
    needed=ancestors(plan,step)
    selected={row['id']:row for row in rows if row['id'] in needed}
    if any(name not in selected or selected[name]['status']!='passed' for name in needed):
        raise ValueError('Required workflow gates have not passed; no effect can be approved.')
    for row in selected.values():verify_artifacts(row)
    payload=dict(plan=plan.identity,step=step,artifacts=[a for row in selected.values() for a in row.get('artifacts',[])])
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Approval:
    step: str
    identity: str


def approve(plan,step,report):
    if report['plan_identity']!=plan.identity:raise ValueError('Review belongs to different source/settings.')
    return Approval(step,review_identity(plan,step,report['phases']))


def recover(plan,report,*,reconcile=None):
    if report.get('schema')!=1 or report.get('plan_identity')!=plan.identity:
        raise ValueError('Result schema or plan identity changed; preserve the original run.')
    effects={phase.id:phase.effect if phase.effect!='inherit' else plan.effect for phase in plan.phases}
    rows=[]
    for original in report['phases']:
        row=dict(original)
        if row['status']=='running':
            row['status']='unknown' if effects[row['id']] in EXTERNAL else 'interrupted'
        if row['status']=='passed':verify_artifacts(row)
        if row['status']=='unknown':
            if reconcile is None:
                raise ValueError('Uncertain external operation requires reconciliation before retry: '+row['id'])
            receipt=reconcile(row['id'],row)
            if receipt.get('status') not in {'passed','not-performed'}:
                raise ValueError('Remote outcome remains unknown; no duplicate action was started.')
            row.update(status='passed' if receipt['status']=='passed' else 'interrupted',receipt=receipt)
        rows.append(row)
    return rows
