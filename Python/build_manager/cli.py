"""Argument-based planning, execution and bounded evidence for automation."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import signal
from threading import Event, Lock

from commonUtils.runtime.operations import OperationCancelled

from .api import (API_VERSION, ManagerAPI, plan_info, read_logs, read_status,
                  review_run, run_plan, summarize)
from .models import Plan
from .redaction import Redactor


class ArgumentError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def assignments(values):
    result = {}
    for value in values:
        key, separator, text = value.partition('=')
        if not separator or not key or key in result:
            raise ValueError('Expected distinct NAME=VALUE arguments.')
        result[key] = text
    return result


def redact(value):
    if isinstance(value, str):
        filter_text = Redactor()
        return ''.join(filter_text(line) for line in value.splitlines(keepends=True))
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def emit(value):
    print(json.dumps(redact(value), ensure_ascii=True), flush=True)


@contextmanager
def cancellation():
    cancelled = Event()
    previous = {}
    try:
        for name in (signal.SIGINT, signal.SIGTERM):
            previous[name] = signal.signal(name, lambda *_: cancelled.set())
        yield cancelled
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


def parser_for_cli():
    parser = Parser(description=__doc__)
    parser.add_argument('--registry', type=Path, help='Explicit private config directory (before command)')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='List project registrations')
    sub.add_parser('add', help='Register a trusted project checkout').add_argument('path', type=Path)
    for name in ('select', 'remove', 'trust', 'inspect'):
        sub.add_parser(name).add_argument('project')
    locate = sub.add_parser('locate')
    locate.add_argument('project')
    locate.add_argument('path', type=Path)
    for name in ('capabilities', 'inputs', 'history', 'presets'):
        command = sub.add_parser(name, help={
            'capabilities': 'Discover declared operations, suites, inputs and host backends',
            'inputs': 'Query trusted adapter input defaults and dynamic choices',
            'history': 'List recent project-owned runs', 'presets': 'List saved and suggested project presets'}[name])
        command.add_argument('--project')
        if name == 'history':
            command.add_argument('--limit', type=int, default=20)
    plan = sub.add_parser('plan', help='Prepare a project-owned operation without executing it')
    plan.add_argument('--project')
    plan.add_argument('--preset', help='Use a saved or suggested project preset')
    plan.add_argument('--operation')
    plan.add_argument('--target')
    plan.add_argument('--backend')
    plan.add_argument('--pattern', default='')
    plan.add_argument('--suite', help='Project-declared test suite ID')
    journey = sub.add_parser('journey', help='Prepare multi-platform validation/delivery')
    journey.add_argument('--project')
    journey.add_argument('--goal', choices=('validate', 'deliver'), default='validate')
    journey.add_argument('--platform', action='append', default=[], dest='platforms')
    journey.add_argument('--destination', action='append', default=[], dest='destinations')
    journey.add_argument('--execution', action='append', default=[], help='Platform=backend')
    for command in (plan, journey):
        command.add_argument('--revision', default='working-tree')
        command.add_argument('--release-tag', default='')
        command.add_argument('--run-value', action='append', default=[], help='Declared field=value for this run only')
        command.add_argument('--output', type=Path, required=True, help='Prepared plan JSON file')
    sub.choices['plan'].add_argument('--exclude-destination', action='append', default=[],
                                    help='Omit a saved preset delivery destination for this run only')
    sub.add_parser('show-plan', help='Read a trusted plan without executing it').add_argument('plan', type=Path)
    storage = sub.add_parser('storage', help='List or explicitly remove adapter-owned generated outputs')
    storage.add_argument('--project')
    storage.add_argument('--delete', action='append', default=[], metavar='GROUP=NAME',
                         help='Exact group and direct output name from storage inventory; repeat for each output')
    storage.add_argument('--confirm', action='store_true', help='Confirm reviewed generated-output deletion')
    retry = sub.add_parser('retry-device', help='Prepare a separate, explicit retry of an uncertain device install')
    retry.add_argument('run', type=Path)
    retry.add_argument('--step', required=True)
    retry.add_argument('--output', type=Path, required=True, help='New plan file; does not execute the install')
    save = sub.add_parser('save-preset', help='Save project choices in the existing GUI/CLI registry')
    save.add_argument('name')
    save.add_argument('--project')
    save.add_argument('--file', type=Path, required=True, help='JSON object in the existing saved-selection schema')
    save.add_argument('--replace', action='store_true')
    start = sub.add_parser('start', help='Prepare and run a saved project preset; delivery still pauses for review')
    start.add_argument('--project')
    start.add_argument('--preset', required=True)
    start.add_argument('--run-value', action='append', default=[], help='Declared field=value for this run only')
    start.add_argument('--exclude-destination', action='append', default=[], help='Omit one delivery destination for this run; keeps all platform validation')
    start.add_argument('--output', type=Path, help='Fresh run directory; defaults to project results')
    run = sub.add_parser('run', help='Execute a reviewed trusted plan and return a compact outcome')
    run.add_argument('plan', type=Path)
    run.add_argument('--output', type=Path, required=True, help='Fresh run directory')
    resume = sub.add_parser('resume', help='Continue the retained plan in an existing run directory')
    resume.add_argument('output', type=Path)
    for command in (run, resume, start):
        command.add_argument('--expect-identity', help='Require the reviewed plan SHA256')
        command.add_argument('--confirm', action='store_true', help='Confirm authorized external effects')
        command.add_argument('--events', action='store_true', help='Stream JSONL events before the final result')
    resume.add_argument('--approval-identity', action='append', default=[], help='Reviewed pending STEP=SHA256 from review')
    resume.add_argument('--engine-review-identity', help='Explicitly reviewed old/new engine identity from review; preserves provenance')
    for name in ('status', 'logs', 'review'):
        command = sub.add_parser(name, help={
            'status': 'Read a compact retained outcome', 'logs': 'Read a bounded step log tail',
            'review': 'Verify prepared artifacts and obtain delivery review identities'}[name])
        command.add_argument('output', type=Path, help='Run directory')
        if name == 'status':
            command.add_argument('--full', action='store_true', help='Return complete result.json evidence')
        if name == 'logs':
            command.add_argument('--step', required=True)
            command.add_argument('--tail-lines', type=int, default=40)
            command.add_argument('--max-bytes', type=int, default=16384)
    return parser


def execute(args, api):
    registry = api.registry
    command = args.command
    if command == 'list':
        return registry.read()
    if command == 'add':
        return dict(registration=registry.add(args.path))
    if command == 'locate':
        registry.locate(args.project, args.path)
        return dict(status='located')
    if command == 'inspect':
        row, descriptor = registry.resolve(args.project)
        return dict(registration=row, descriptor=descriptor)
    if command in ('select', 'remove', 'trust'):
        getattr(registry, command)(args.project)
        return dict(status=command)
    if command in ('capabilities', 'inputs', 'presets'):
        return getattr(api, command)(args.project)
    if command == 'storage':
        if not args.delete:
            if args.confirm:
                raise ArgumentError('Choose exact storage outputs with --delete before confirming.')
            return dict(entries=api.storage_inventory(args.project))
        selections = {}
        for value in args.delete:
            group, separator, name = value.partition('=')
            if not separator or not group or not name:
                raise ArgumentError('Storage deletion requires GROUP=NAME from the inventory.')
            selections.setdefault(group, []).append(name)
        return api.delete_storage(selections, project=args.project, confirmed=args.confirm)
    if command == 'history':
        return api.history(args.project, args.limit)
    if command == 'save-preset':
        if args.file.stat().st_size > 262144:
            raise ValueError('Preset input is too large.')
        return api.save_preset(args.name, json.loads(args.file.read_text()),
                               project=args.project, replace=args.replace)
    if command == 'plan' and args.preset:
        if any((args.operation, args.target, args.backend, args.suite, args.pattern,
                args.release_tag, args.revision != 'working-tree')):
            raise ValueError('Preset planning uses its saved choices; do not combine explicit operation arguments.')
        prepared = api.prepare_preset(args.preset, project=args.project,
                run_overrides=assignments(args.run_value) if args.run_value else None,
                exclude_destinations=args.exclude_destination)
        prepared.save(args.output)
        return dict(plan=str(args.output.resolve()), identity=prepared.identity)
    if command == 'plan' and args.exclude_destination:
        raise ArgumentError('Destination exclusions require --preset.')
    if command in ('plan', 'journey'):
        options = dict(revision=args.revision, release_tag=args.release_tag)
        if args.run_value:
            options['run_overrides'] = assignments(args.run_value)
        if command == 'plan':
            if not all((args.operation, args.target, args.backend)):
                raise ArgumentError('Plan needs --preset or --operation, --target and --backend.')
            if args.suite:
                options['suite'] = args.suite
            prepared = api.prepare_plan(args.operation, args.target, args.backend, project=args.project,
                                        pattern=args.pattern, **options)
        else:
            if args.execution:
                choices = assignments(args.execution)
                if set(choices) - set(args.platforms):
                    raise ValueError('Execution choices must name selected platforms.')
                from .bridge import ProjectBridge
                capability = ProjectBridge(registry, args.project).journey_capability
                options['backends'] = {target: choices.get(target, capability['platforms'][target]['backend'])
                                       for target in args.platforms}
            prepared = api.prepare_journey(args.goal, args.platforms, args.destinations, project=args.project, **options)
        prepared.save(args.output)
        return dict(plan=str(args.output.resolve()), identity=prepared.identity)
    if command == 'show-plan':
        return plan_info(Plan.load(args.plan))
    if command == 'retry-device':
        from .device_retry import prepare
        if args.output.exists():
            raise ValueError('Choose a new retry plan path; preserve existing evidence.')
        prepared = prepare(args.run, args.step)
        prepared.save(args.output)
        return dict(plan=str(args.output.resolve()), identity=prepared.identity, warning=prepared.settings['warning'])
    if command == 'status':
        return read_status(args.output, full=args.full)
    if command == 'logs':
        return read_logs(args.output, args.step, tail_lines=args.tail_lines, max_bytes=args.max_bytes)
    if command == 'review':
        with cancellation() as cancelled:
            return review_run(args.output, cancelled=cancelled)
    if command in ('run', 'resume', 'start'):
        if command == 'start':
            from datetime import datetime, timezone
            from uuid import uuid4
            if args.output is None:
                bridge = api._project(args.project)
                args.output = bridge.results_directory / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8])
            if args.output.exists():
                raise ValueError('Use a fresh output directory or resume the retained run.')
            prepared = api.prepare_preset(args.preset, project=args.project,
                run_overrides=assignments(args.run_value) if args.run_value else None,
                exclude_destinations=args.exclude_destination)
        lock = Lock()
        def event(value):
            with lock:
                emit(dict(cli_schema=API_VERSION, type='event', event=value))
        with cancellation() as cancelled:
            report = run_plan(prepared if command == 'start' else args.output / 'plan.json' if command == 'resume' else args.plan, args.output,
                              confirmed=args.confirm, resume=command == 'resume',
                              approval_identities=assignments(args.approval_identity) if command == 'resume' else None,
                              expected_identity=args.expect_identity, engine_review=args.engine_review_identity if command == 'resume' else None, cancelled=cancelled,
                              event=event if args.events else None)
        return summarize(report, args.output)
    raise ValueError('Unsupported command.')


def main(argv=None):
    command = None
    try:
        args = parser_for_cli().parse_args(argv)
        command = args.command
        result = execute(args, ManagerAPI(args.registry))
        status = result.get('status')
        code = ({'passed': 0, 'awaiting_review': 3, 'cancelled': 130}.get(status, 1)
                if command in ('run', 'resume', 'start') else 0)
        # Existing registration/planning fields stay at the top level.
        emit(dict(result, cli_schema=API_VERSION, command=command, ok=code == 0))
        return code
    except (KeyboardInterrupt, OperationCancelled):
        emit(dict(cli_schema=API_VERSION, command=command, ok=False,
                  error=dict(code='cancelled', message='Request cancelled.')))
        return 130
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        code = 2 if isinstance(error, ArgumentError) else 1
        emit(dict(cli_schema=API_VERSION, command=command, ok=False,
                  error=dict(code='invalid_arguments' if code == 2 else 'request_failed', message=str(error))))
        return code


if __name__ == '__main__':
    raise SystemExit(main())
