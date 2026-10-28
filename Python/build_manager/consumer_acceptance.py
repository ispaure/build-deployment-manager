"""Prepare an ordinary manager plan for explicit cross-consumer test commands.

No sibling discovery, pin replacement, interpreter installation or custom executor.
The caller supplies test scope and project-owned output/storage policy.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from commonUtils.runtime.streams import file_sha256
from .identity import checkout_identity
from .local import inspect_python
from .models import Phase, Plan
from .profiles import save_json


def capture(config):
    if config.get('schema') != 1 or not isinstance(config.get('checks'), list) or not config['checks']:
        raise ValueError('Acceptance needs schema 1 and explicit checks.')
    baseline = Path(config['baseline']).resolve()
    identity = checkout_identity(baseline)
    if not identity.get('commit'):
        raise ValueError('The explicit baseline must be a Git checkout.')
    checks = {}
    for row in config['checks']:
        key = row.get('id', '')
        if not re.fullmatch(r'[a-zA-Z0-9][\w.-]*', key) or key in checks:
            raise ValueError('Acceptance check IDs must be unique.')
        root, interpreter = Path(row['root']).resolve(), Path(row['interpreter']).absolute()
        source = checkout_identity(root)
        if not source.get('commit'):
            raise ValueError('Every consumer must name its Git checkout.')
        if row.get('branch'):
            import subprocess
            branch = subprocess.check_output(['git', '-C', str(root), 'branch', '--show-current'], text=True).strip()
            if branch != row['branch']:
                raise ValueError(key + ': unexpected consumer branch.')
        argv = row.get('argv')
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            raise ValueError('Acceptance uses explicit argument arrays after the interpreter.')
        environment = row.get('environment', {})
        if not isinstance(environment, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in environment.items()):
            raise ValueError('Acceptance environment must contain text values.')
        from .credentials import reject_secrets
        reject_secrets(environment)
        shared = Path(row['shared']).resolve() if row.get('shared') else baseline
        checks[key] = dict(root=str(root), source=source, shared=str(shared),
            shared_source=checkout_identity(shared), interpreter=str(interpreter),
            toolchain=inspect_python(interpreter, row.get('distributions', ())),
            argv=argv, environment=environment, branch=row.get('branch', ''))
    return dict(baseline=str(baseline), baseline_source=identity, checks=checks)


def prepare(config, directory):
    """Capture selected sources/environments and emit one existing Plan contract."""
    directory = Path(directory).absolute()
    if directory.exists():
        raise ValueError('Choose a fresh acceptance evidence directory.')
    source = capture(config)
    directory.mkdir(parents=True)
    captured = directory / 'inputs.json'
    save_json(captured, dict(schema=1, config=config, source=source))
    verify = (sys.executable, '-m', 'build_manager.consumer_acceptance', 'verify',
              '--capture', str(captured), '--sha256', file_sha256(captured))
    cwd = str(Path(__file__).resolve().parents[2])
    phases = [Phase('verify-inputs', verify, cwd, effect='inspect', timeout=120)]
    for key, row in source['checks'].items():
        # Explicit source roots, never the planner's inherited PYTHONPATH.
        environment = {'PYTHONPATH': '', 'PYTHONHOME': '', **row['environment']}
        phases.append(Phase(key, (row['interpreter'], *row['argv']), row['root'],
            environment=environment, dependencies=('verify-inputs',), effect='test', timeout=1800))
    phases.append(Phase('verify-completion', verify, cwd,
        dependencies=tuple(row.id for row in phases[1:]), always=True, effect='inspect', timeout=120))
    plan = Plan('Consumer acceptance', 'Explicit portable compatibility checks', source,
        tuple(phases), str(directory / 'workspace'), max_workers=1)
    plan.save(directory / 'plan.json')
    return plan


def verify(path, digest):
    path = Path(path)
    if file_sha256(path) != digest:
        raise ValueError('Acceptance input capture changed.')
    value = json.loads(path.read_text())
    if value.get('schema') != 1 or capture(value['config']) != value['source']:
        raise ValueError('A baseline, consumer, branch or interpreter changed; prepare fresh acceptance.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    plan = commands.add_parser('plan')
    plan.add_argument('--config', type=Path, required=True)
    plan.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--capture', type=Path, required=True)
    check.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'plan':
        prepare(json.loads(args.config.read_text()), args.output)
        print(args.output / 'plan.json')
    else:
        verify(args.capture, args.sha256)


if __name__ == '__main__':
    main()
