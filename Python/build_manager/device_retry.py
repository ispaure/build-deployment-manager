"""Explicit, separately reviewed device reinstallation; never resume an unknown intent."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from .history import load_run
from .models import Phase, Plan
from .workflows import ancestors, verify_artifacts


def candidates(plan, report):
    states = {row['id']: row['status'] for row in report['phases']}
    if report['status'] not in {'unknown', 'failed', 'cancelled'}:
        return []
    return [phase for phase in plan.phases if phase.effect == 'deploy'
            and states.get(phase.id) == 'unknown' and phase.artifacts
            and all(states.get(key) == 'passed' for key in ancestors(plan, phase.id))
            and all(path in phase.argv for path in phase.artifacts)]


def inspect(output, step, expected=None):
    output = Path(output).resolve()
    plan, report = load_run(output / 'result.json')
    phase = next((item for item in candidates(plan, report) if item.id == step), None)
    if phase is None:
        raise ValueError('Choose an uncertain device installation with passed preparation and declared receipt outputs.')
    needed = ancestors(plan, step)
    rows = [row for row in report['phases'] if row['id'] in needed]
    for row in rows:
        verify_artifacts(row)
    digest = hashlib.sha256(json.dumps(dict(plan=plan.identity, report=report, step=step), sort_keys=True).encode()).hexdigest()
    if expected is not None and expected != digest:
        raise ValueError('Original run changed; review the device retry again.')
    return plan, phase, rows, digest


def prepare(output, step, *, authorized=False):
    """Produce a fresh plan with fresh receipt paths and an input-verification gate."""
    plan, phase, rows, digest = inspect(output, step)
    workspace = Path(plan.workspace) / 'explicit-device-retries' / uuid4().hex
    paths = {path: str(workspace / ('receipt-' + str(index) + Path(path).suffix))
             for index, path in enumerate(phase.artifacts)}
    artifacts = tuple(dict.fromkeys(artifact.get('original_path', artifact['path'])
                                   for row in rows for artifact in row.get('artifacts', [])))
    if not artifacts:
        raise ValueError('A device retry requires retained prepared-artifact evidence.')
    verify = Phase('verify-original-inputs',
        (sys.executable, '-m', 'build_manager.device_retry', str(Path(output).resolve()), step, digest),
        str(Path(__file__).resolve().parents[2]), effect='inspect', kind='verification', artifacts=artifacts,
        label='Verify original prepared app and retry provenance')
    retry = replace(phase, dependencies=(verify.id,), waits_for=(),
        argv=tuple(paths.get(arg, arg) for arg in phase.argv), artifacts=tuple(paths.values()),
        artifact_types={paths.get(key, key): value for key, value in phase.artifact_types.items()},
        approval_required=not authorized, label='Explicit retry: ' + (phase.label or phase.id))
    return Plan(plan.project, 'Explicit device install retry', plan.source, (verify, retry), str(workspace),
        backend=plan.backend, effect='deploy', secret_environment=plan.secret_environment,
        resource_locks=tuple(dict.fromkeys((*plan.resource_locks, str(Path(plan.workspace) / 'operation.lock')))),
        capacities=plan.capacities, settings={'original_run': str(Path(output).resolve()),
            'original_plan_identity': plan.identity, 'original_step': step, 'retry_review_identity': digest,
            'warning': 'The earlier install may have completed. This explicitly requests another installation of the same prepared app; its unknown outcome remains unchanged.'},
        adapter=plan.adapter)


if __name__ == '__main__':
    _, _, rows, digest = inspect(*sys.argv[1:])
    print(json.dumps(dict(status='verified', identity=digest, prerequisites=len(rows))))
