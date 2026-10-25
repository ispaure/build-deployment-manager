"""Project registration and planning without importing Qt."""
import argparse
import json
from pathlib import Path
import sys

from .registry import Registry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, help='Explicit private config directory')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    for name in ('add',):
        sub.add_parser(name).add_argument('path', type=Path)
    for name in ('select','remove','trust','inspect'):
        sub.add_parser(name).add_argument('project')
    locate = sub.add_parser('locate'); locate.add_argument('project'); locate.add_argument('path',type=Path)
    plan = sub.add_parser('plan')
    plan.add_argument('--project'); plan.add_argument('--operation', required=True)
    plan.add_argument('--target', required=True); plan.add_argument('--backend', required=True)
    plan.add_argument('--revision', default='working-tree'); plan.add_argument('--pattern', default='')
    plan.add_argument('--release-tag', default=''); plan.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    registry = Registry(args.registry)
    try:
        if args.command == 'list':
            result = registry.read()
        elif args.command == 'add':
            result = dict(registration=registry.add(args.path))
        elif args.command == 'locate':
            registry.locate(args.project,args.path); result = dict(status='located; trust required')
        elif args.command == 'inspect':
            row, descriptor = registry.resolve(args.project); result = dict(registration=row, descriptor=descriptor)
        elif args.command == 'plan':
            from .bridge import ProjectBridge
            plan = ProjectBridge(registry, args.project).make_plan(args.operation, args.target, args.backend,
                revision=args.revision, pattern=args.pattern, release_tag=args.release_tag)
            plan.save(args.output); result = dict(plan=str(args.output), identity=plan.identity)
        else:
            getattr(registry,args.command)(args.project); result=dict(status=args.command)
        print(json.dumps(result,indent=2)); return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error),file=sys.stderr); return 1
