"""Explicit scaffolding and staged readiness diagnostics; never runs a workload."""
import json
from pathlib import Path
import shutil
import sys

from .registry import inspect


def scaffold(root, name, project_id, argv):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Choose an existing project directory.')
    descriptor = dict(schema=1, adapter_api=1, project_id=project_id, name=name,
        commands=dict(source=[], operations={'Check': [dict(id='check', argv=argv, effect='test')]}))
    from .command_project import normalize
    normalize(descriptor)
    # Exclusive create: never overwrite an integration, including a dangling link.
    path = root / 'build-project.json'
    with path.open('x') as stream:
        json.dump(descriptor, stream, indent=2)
        stream.write('\n')
    return dict(path=str(path), status='created', next='Declare public source paths and review the command, then add this project.')


def readiness(root, descriptor=None):
    """Static facts only. An existing interpreter is not an adapter import check."""
    root = Path(root).resolve()
    if descriptor is None:
        descriptor, _ = inspect(root)
    if 'commands' in descriptor:
        from .command_project import inventory
        try:
            inventory(root, descriptor['commands']['source'])
        except (OSError, ValueError) as error:
            return dict(stage='prerequisites_missing', ready=False, missing=[], message=str(error))
        missing = []
        for rows in descriptor['commands']['operations'].values():
            for row in rows:
                exe = row['argv'][0].replace('{project}', str(root))
                if '{source}' in exe or '{output}' in exe:
                    continue  # Captured executable validated when preparing the operation.
                if not shutil.which(exe):
                    missing.append(exe)
        return dict(stage='configured' if not missing else 'prerequisites_missing',
                    ready=not missing, missing=sorted(set(missing)),
                    message='Commands configured; SDKs and operation readiness are checked when preparing/running work.' if not missing else 'Command executables missing: ' + ', '.join(missing))
    interpreter = descriptor['interpreter']
    python = root / (interpreter[sys.platform] if isinstance(interpreter, dict) else interpreter)
    paths = [python] + ([root / descriptor['bridge']] if descriptor.get('bridge') else [])
    missing = [str(p) for p in paths if not p.is_file()]
    return dict(stage='files_present' if not missing else 'prerequisites_missing', ready=not missing,
                missing=missing, message='Adapter files found; imports and SDK readiness have not been checked.' if not missing
                else 'Missing project interpreter or bridge: ' + ', '.join(missing))


def check_adapter(registry, project=None, *, prepare=False):
    """Explicit trusted settings probe; optional planning matrix without execution.

    Preparation may capture sources or invoke project retention. It is opt-in.
    Settings writes, verification plans and external workload commands are never run.
    """
    from .bridge import ProjectBridge
    bridge = ProjectBridge(registry, project)
    result = readiness(bridge.root)
    if not result['ready']:
        return dict(result, status='failed')
    rows = bridge.call('settings', timeout=30)
    if not isinstance(rows, dict) or any(not isinstance(v, dict) or 'value' not in v for v in rows.values()):
        raise ValueError('Adapter settings must map field names to rows with values.')
    checks = []
    if prepare:
        for target in bridge.platforms:
            for operation in bridge.operations_for(target):
                for backend in bridge.backend_options(target, operation):
                    selections = [''] + [row['id'] for row in bridge.test_suites
                        if target in row['platforms'] and operation in row['operations']]
                    for suite in selections:
                        choice = dict(target=target, operation=operation, backend=backend, suite=suite)
                        try:
                            plan = bridge.make_plan(operation, target, backend, **({'suite': suite} if suite else {}))
                            if plan.project != bridge.descriptor['name']:
                                raise ValueError('Plan belongs to another project.')
                            checks.append(dict(choice, status='prepared', identity=plan.identity))
                        except (OSError, ValueError, RuntimeError, KeyError) as error:
                            checks.append(dict(choice, status='failed', error=str(error)))
        if not checks:
            checks.append(dict(status='failed', error='No operation/backend combinations are available on this host.'))
    return dict(stage='adapter_loaded', status='failed' if any(c['status'] == 'failed' for c in checks) else 'passed',
                settings_fields=len(rows), plans=checks, workloads_executed=False,
                message='Settings protocol loaded. Only explicitly prepared combinations have been checked; native readiness is not certified.')
