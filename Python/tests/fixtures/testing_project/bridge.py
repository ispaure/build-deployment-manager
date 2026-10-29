"""Minimal API-1 test adapter. See docs/development/adding-project-tests.md."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from build_manager import Plan
from build_manager.test_manifest import phases

ROOT = Path(__file__).resolve().parent


def make_plan(values):
    if (values.get('operation') != 'Test' or values.get('target') != 'host'
            or values.get('backend') != 'Local'):
        raise ValueError('Select Test / host / Local.')
    if values.get('suite', '') not in ('', 'labels'):
        raise ValueError('Unknown suite; select labels or the complete project.')
    if values.get('pattern') or values.get('revision', 'working-tree') != 'working-tree':
        raise ValueError('This learning adapter supports complete working-tree tests only.')
    workspace = ROOT / 'test-results' / uuid4().hex
    snapshot = workspace / 'source'
    snapshot.mkdir(parents=True)
    sources = [ROOT / name for name in ('labels.py', 'bridge.py', 'build-project.json', 'build-tests.json')]
    sources.extend(sorted((ROOT / 'tests').rglob('*.py')))
    inputs = {}
    for path in sources:
        if any((ROOT / part).is_symlink() for part in (path.relative_to(ROOT), *path.relative_to(ROOT).parents)):
            raise ValueError('Example sources must be ordinary files.')
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError('Example source escapes the project.')
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        data = path.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        inputs[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    checks = phases(snapshot, 'validation', {'project': sys.executable},
                    ('-m', 'build_manager.reporting', '--start', '{directory}'))
    reported = []
    for check in checks:
        report = workspace / 'reports' / (check.id + '.xml')
        test_root = snapshot / 'tests'
        inventory = tuple(p.relative_to(test_root).as_posix()
                          for p in sorted(test_root.rglob('test*.py')))
        reported.append(replace(check,
            argv=(*check.argv, '--output', str(report), '--suite', check.id, '--fail-on-skip'),
            artifacts=(str(report),), artifact_types={str(report): 'junit'},
            test_files=inventory))
    return Plan(project='Testing walkthrough', operation='Test',
                source={'description': 'Copied public example inputs; no reuse or delivery',
                        'files_sha256': inputs},
                phases=tuple(reported), workspace=str(workspace), backend='Local')


def main():
    request = json.load(sys.stdin)
    if request.get('schema') != 1:
        raise ValueError('Expected bridge request schema 1.')
    action = request.get('action')
    values = request.get('values', {})
    if action == 'plan':
        result = make_plan(values).data()
    elif action == 'settings':
        result = {}
    elif action == 'save_settings':
        if values.get('changes'):
            raise ValueError('This example has no project settings.')
        result = {}
    elif action == 'verification':
        result = make_plan(dict(operation='Test', target='host', backend='Local')).data()
    else:
        raise ValueError('Unsupported example bridge action.')
    print(json.dumps(dict(schema=1, result=result)))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
