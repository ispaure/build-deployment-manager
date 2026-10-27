"""Read-only review of selected old checks, never a replacement test outcome.

Projects separately decide coverage applicability to new source and toolchains.
This module verifies only the original evidence and its complete dependency set.
"""
import hashlib
import json
from pathlib import Path

from commonUtils.runtime.streams import file_sha256

from .history import load_run
from .retention import linked
from .workflows import EXTERNAL, ancestors, verify_artifacts


def verify_checks(output, plan_identity, steps, *, expect_review=None):
    output = Path(output)
    if linked(output) or any(linked(output/name) for name in ('plan.json', 'result.json')):
        raise ValueError('Retained checks cannot use linked run records.')
    evidence = {str(output/name): file_sha256(output/name) for name in ('plan.json', 'result.json')}
    plan, report = load_run(output/'result.json')
    if plan.identity != plan_identity or report.get('source') != plan.source:
        raise ValueError('Retained checks belong to a different source or plan.')
    phases = {phase.id: phase for phase in plan.phases}
    steps = tuple(steps)
    if not steps or len(set(steps)) != len(steps) or any(step not in phases for step in steps):
        raise ValueError('Select unique declared retained check IDs.')
    selected = set(steps)
    for step in steps:
        selected.update(ancestors(plan, step))
    rows = {row['id']: row for row in report['phases']}
    checks = []
    for phase in plan.phases:
        if phase.id not in selected:
            continue
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        row = rows.get(phase.id, {})
        if effect in EXTERNAL or effect not in {'test', 'build', 'inspect'}:
            raise ValueError('External effects cannot become retained test evidence.')
        if row.get('status') != 'passed':
            raise ValueError('Selected check or prerequisite did not pass: ' + phase.id)
        artifacts = row.get('artifacts', [])
        if (len(artifacts) != len(phase.artifacts) or
                [a.get('original_path', a.get('path')) for a in artifacts] != list(phase.artifacts)):
            raise ValueError('Retained artifact inventory differs from the original check.')
        verify_artifacts(row)
        if row.get('log') != phase.id+'.log' or linked(output/row['log']):
            raise ValueError('Retained check log is missing or linked.')
        log = output/row['log']
        evidence[str(log)] = file_sha256(log)
        for artifact in artifacts:
            for key in ('path', 'original_path'):
                path = artifact.get(key, artifact['path'])
                if linked(Path(path)):
                    raise ValueError('Retained check artifacts cannot be linked.')
                evidence[path] = artifact['sha256']
        checks.append(dict(id=phase.id, effect=effect, kind=phase.kind, status='passed'))
    if any(file_sha256(path) != digest for path, digest in evidence.items()):
        raise ValueError('Retained check records changed during verification.')
    receipt = dict(schema=1, scope='original checks only', plan_identity=plan.identity,
                   source=plan.source, engine=report.get('engine'), requested_steps=list(steps),
                   checks=checks, evidence=evidence, fresh_execution=False,
                   authorizes_source_reuse=False, original_records_unchanged=True)
    receipt['identity'] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    if expect_review is not None and receipt['identity'] != expect_review:
        raise ValueError('Retained check evidence changed; review its new identity.')
    return receipt


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan-identity', required=True)
    parser.add_argument('--step', action='append', required=True)
    parser.add_argument('--expect-review')
    args = parser.parse_args()
    print(json.dumps(verify_checks(args.output, args.plan_identity, args.step,
                                  expect_review=args.expect_review), indent=2))


if __name__ == '__main__':
    main()
