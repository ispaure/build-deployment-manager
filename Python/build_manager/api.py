"""Headless automation API. Project policy remains in isolated adapter processes."""
from collections import Counter
from pathlib import Path
from threading import Event

from .executor import Executor
from .history import load_run, read_report, recent_runs
from .models import Plan
from .registry import Registry
from .workflows import EXTERNAL, ancestors, approve, recover

API_VERSION = 1


class ManagerAPI:
    def __init__(self, registry=None):
        self.registry = Registry(registry)

    def _project(self, project):
        from .bridge import ProjectBridge
        return ProjectBridge(self.registry, project)

    def capabilities(self, project=None):
        """Discover host-specific choices without running project code."""
        bridge = self._project(project)
        return dict(project=bridge.key, registration=bridge.row,
                    descriptor=bridge.descriptor,
                    targets={target: {operation: list(bridge.backend_options(target, operation))
                        for operation in bridge.operations_for(target)} for target in bridge.platforms},
                    journey=bridge.journey_capability)

    def inputs(self, project=None):
        """Explicitly query the adapter for dynamic non-secret input choices."""
        bridge = self._project(project)
        return dict(fields=bridge.run_fields, defaults=bridge.run_defaults(), choices=bridge.run_choices())

    def prepare_plan(self, operation, target, backend, *, project=None, **values):
        return self._project(project).make_plan(operation, target, backend, **values)

    def prepare_journey(self, goal, platforms, destinations, *, project=None, **values):
        return self._project(project).make_journey(goal, platforms, destinations, **values)

    def presets(self, project=None):
        bridge = self._project(project)
        return dict(project=bridge.key, saved=bridge.row.get('presets', {}),
                    suggested=bridge.workflow_presets)

    def save_preset(self, name, choices, *, project=None, replace=False):
        bridge = self._project(project)
        if name in bridge.row.get('presets', {}) and not replace:
            raise ValueError('Preset already exists; use explicit replacement after review.')
        self.registry.save_preset(bridge.key, name, choices)
        return dict(project=bridge.key, preset=name.strip(), choices=choices)

    def prepare_preset(self, name, *, project=None):
        bridge = self._project(project)
        saved = bridge.row.get('presets', {})
        if name not in saved and name not in bridge.workflow_presets:
            raise ValueError('Unknown project preset: ' + name)
        choices = saved[name] if name in saved else bridge.workflow_presets[name]
        self.registry.validate_selections(choices)
        options = dict(revision=choices.get('revision', 'working-tree'),
                       pattern=choices.get('pattern', ''), release_tag=choices.get('release_tag', ''),
                       build_override=str(choices['build_override']) if choices.get('build_override') else '')
        if choices.get('run_overrides'):
            options['run_overrides'] = dict(choices['run_overrides'])
        goal = choices.get('goal', 'advanced')
        if goal in ('validate', 'deliver'):
            if not bridge.journey_capability:
                raise ValueError('This preset needs project-declared combined journeys.')
            platforms = choices.get('selected_platforms', [])
            backends = choices.get('platform_backends', {})
            if set(backends) - set(bridge.platforms):
                raise ValueError('Preset contains unknown execution platforms.')
            if backends:
                options['backends'] = {target: backends.get(target, bridge.journey_capability['platforms'][target]['backend'])
                                       for target in platforms}
            return bridge.make_journey(goal, platforms,
                choices.get('selected_destinations', []) if goal == 'deliver' else [], **options)
        if goal != 'advanced':
            raise ValueError('Unknown preset goal.')
        if choices.get('suite'):
            options['suite'] = choices['suite']
        run_options = choices.get('run_options', {})
        if set(run_options) - set(bridge.run_options):
            raise ValueError('Preset contains unknown project run options.')
        options.update(run_options)
        try:
            operation, platform, backend = (choices[key] for key in ('operation', 'platform', 'backend'))
        except KeyError as error:
            raise ValueError('Advanced presets need operation, platform and backend.') from error
        return bridge.make_plan(operation, platform, backend, **options)

    def history(self, project=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('History limit must be 1–100.')
        bridge = self._project(project)
        return dict(directory=str(bridge.results_directory), runs=recent_runs(bridge.results_directory, limit))


def plan_info(plan):
    return dict(identity=plan.identity, plan=plan.data())


def summarize(report, output):
    """Compact outcome; complete evidence stays in result.json and per-step logs."""
    phases = []
    for row in report['phases']:
        phase = {key: row[key] for key in ('id', 'status', 'required', 'seconds', 'exit_code', 'log') if key in row}
        for key in ('error', 'cleanup_error', 'reason', 'summary'):
            if key in row:
                phase[key] = str(row[key])[-3000:]
        failures = [case for case in row.get('tests', []) if case['status'] in {'failed', 'error'}]
        if failures:
            phase['failed_tests'] = [{key: str(case[key])[-2000:] for key in
                ('name', 'classname', 'status', 'message')} for case in failures[:20]]
            phase['failed_test_count'] = len(failures)
        phases.append(phase)
    return dict(status=report['status'], project=report.get('project'), operation=report.get('operation'),
                plan_identity=report.get('plan_identity'), seconds=report.get('seconds'),
                error=str(report.get('error', ''))[-3000:], counts=dict(Counter(row['status'] for row in phases)),
                phases=phases, output=str(Path(output).resolve()),
                report=str(Path(output).resolve() / 'result.json'))


def read_status(output, *, full=False):
    report = read_report(Path(output) / 'result.json')
    return report if full else summarize(report, output)


def review_run(output, *, cancelled=None):
    """Verify retained gates/artifacts and return identities, without executing."""
    cancelled = cancelled or Event()
    plan, report = load_run(Path(output) / 'result.json')
    recover(plan, report, cancelled=cancelled.is_set)
    pending = {row['id'] for row in report['phases'] if row['status'] == 'awaiting_review'}
    steps = []
    needed = set()
    for phase in plan.phases:
        if phase.id in pending and phase.effect in EXTERNAL:
            approval = approve(plan, phase.id, report, cancelled=cancelled.is_set)
            steps.append(dict(step=approval.step, identity=approval.identity))
            needed.update(ancestors(plan, phase.id))
    artifacts = [dict(step=row['id'], artifacts=row.get('artifacts', []))
                 for row in report['phases'] if row['id'] in needed]
    from .identity import runtime_identity, engine_review_identity
    engine = runtime_identity()
    change = None
    if report.get('engine') is not None and report['engine'] != engine:
        change = dict(previous=report['engine'], current=engine,
                      identity=engine_review_identity(report['engine'], engine))
    return dict(**plan_info(plan), status=report['status'], approvals=steps,
                prerequisites=artifacts, engine_change=change)


def run_plan(plan, output, *, confirmed=False, resume=False, approval_identities=None,
             expected_identity=None, cancelled=None, event=None, engine_review=None):
    """Run a trusted Plan/path; reviewed identities authorize only matching pending steps.

    This call blocks until completion or review. Cancellation is a threading.Event.
    Event callbacks run on executor threads and must be thread safe.
    """
    plan = Plan.from_data(plan.data()) if isinstance(plan, Plan) else Plan.load(plan)
    output = Path(output).resolve()
    if expected_identity is not None and plan.identity != expected_identity:
        raise ValueError('Plan identity changed; inspect the current plan before execution.')
    cancelled = cancelled or Event()
    identities = approval_identities or {}
    if not isinstance(identities, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                             for key, value in identities.items()):
        raise ValueError('Approval identities must map step IDs to reviewed SHA256 strings.')
    if engine_review is not None and not resume:
        raise ValueError("Engine continuation review requires resume.")
    approvals = []
    if identities and (not resume or not confirmed):
        raise ValueError('Step approval needs resume and confirmation after artifact/destination review.')
    if resume:
        retained, previous = load_run(Path(output) / 'result.json')
        if retained.identity != plan.identity:
            raise ValueError('Retained plan identity changed; preserve the original run.')
        recover(plan, previous, cancelled=cancelled.is_set)
        pending = {row['id'] for row in previous['phases'] if row['status'] == 'awaiting_review'}
        external = {phase.id for phase in plan.phases if phase.effect in EXTERNAL}
        for step, digest in identities.items():
            if step not in pending or step not in external:
                raise ValueError('Approval must name a pending external step: ' + step)
            permission = approve(plan, step, previous, cancelled=cancelled.is_set)
            if digest != permission.identity:
                raise ValueError('Reviewed artifact identity changed; inspect the current preparation.')
            approvals.append(permission)
    return Executor(cancelled=cancelled, event=event).run(
        plan, output, confirmed=confirmed, resume=resume, approvals=approvals, engine_review=engine_review)


def read_logs(output, step, *, tail_lines=40, max_bytes=16384):
    """Read at most 64 KiB from a declared phase log; never follow arbitrary paths."""
    if type(tail_lines) is not int or not 1 <= tail_lines <= 1000:
        raise ValueError('Log tail must be 1–1000 lines.')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 65536:
        raise ValueError('Log byte limit must be 1–65536.')
    output = Path(output).resolve()
    plan, report = load_run(output / 'result.json')
    if step not in {phase.id for phase in plan.phases}:
        raise ValueError('Unknown plan step: ' + step)
    row = next((row for row in report['phases'] if row['id'] == step), {})
    log = row.get('log')
    if log is None and row.get('status') == 'running':
        # Active intent rows predate the worker's completed log metadata.
        log = step + '.log'
    if log != step + '.log':
        raise ValueError('Step has no retained log yet: ' + step)
    path = output / log
    if path.is_symlink() or path.resolve().parent != output:
        raise ValueError('Log must remain in its run directory.')
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        start = max(0, size - max_bytes)
        stream.seek(start)
        raw = stream.read(max_bytes)
    lines = raw.decode('utf-8', errors='replace').splitlines()
    # Preserve even a partial last line so very long compiler errors stay useful.
    return dict(step=step, log=str(path), text='\n'.join(lines[-tail_lines:]),
                truncated=bool(start or len(lines) > tail_lines), bytes_read=len(raw))
