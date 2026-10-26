"""Sequential phase execution, dependency gates, bounded waits and process cleanup."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import shutil
import subprocess
from threading import Event, Thread
from uuid import uuid4
import time

from commonUtils.runtime.streams import file_sha256
from commonUtils.runtime.operations import OperationCancelled
from .locking import workspace_lock
from .redaction import Redactor


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def signal_group(group, sig):
    try:
        os.killpg(group, sig)
    except PermissionError:
        # Darwin can briefly report EPERM while an orphan group is reaped
        # after SIGTERM. Retry once; never hide a persistent permission error.
        time.sleep(.05)
        os.killpg(group, sig)


def stop_process(process, *, grace=1):
    if os.name == 'nt':
        process.kill_tree()
    else:
        try:
            signal_group(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # A parent can exit before its descendants, leaving inherited output pipes
    # open. Always retire the owned process group, even after parent exit.
    if os.name == 'nt':
        process.kill_tree()
    else:
        try:
            signal_group(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


class Executor:
    def __init__(self, *, cancelled=None, event=None, resource_directory=None):
        self.cancelled = cancelled if cancelled is not None else Event()
        self.event = event or (lambda value: None)
        self.resource_directory = resource_directory

    def run(self, plan, output, *, confirmed=False, resume=False, approvals=(), reconcile=None):
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        from .identity import runtime_identity
        from .models import Plan
        from .resources import Resources
        from .workflows import EXTERNAL, recover, review_identity, verify_artifacts
        plan = Plan.from_data(plan.data())
        if plan.effect in EXTERNAL and not confirmed:
            raise ValueError('This operation requires explicit confirmation after reviewing the plan.')
        engine = runtime_identity()
        if not engine['manager'].get('commit') or not engine['commonUtils'].get('commit'):
            raise ValueError('Execution requires an identifiable manager Git checkout and initialized commonUtils; install it explicitly with pip install --no-deps -e PATH.')
        output = Path(output)
        if resume:
            from .history import read_report
            report = read_report(output/'result.json')
        else:
            output.mkdir(parents=True, exist_ok=False, mode=0o700)
            report = dict(schema=1, engine=engine, project=plan.project, operation=plan.operation,
                          plan_identity=plan.identity, source=plan.source, backend=plan.backend,
                          started_at=timestamp(), status='queued', phases=[])
        if not resume:
            plan.save(output/'plan.json')
        elif report.get('engine') is not None and report['engine'] != engine:
            raise ValueError('Manager/dependency identity changed; inspect a new run or explicitly invalidate old work.')
        def sanitize(value):
            if isinstance(value, str):
                return Redactor(os.environ.get(name) for name in plan.secret_environment)(value)
            if isinstance(value, dict):return {key:sanitize(item) for key,item in value.items()}
            if isinstance(value, (tuple,list)):return [sanitize(item) for item in value]
            return value
        def save():
            from .profiles import save_json
            save_json(output/'result.json',sanitize(report))
        started = time.monotonic()
        from .history import valid_seconds
        previous_seconds = report.get('seconds', 0) if resume else 0
        if not valid_seconds(previous_seconds) or not isinstance(report.get('attempts', []), list):
            raise ValueError('Retained run timing is invalid; preserve and inspect a new run.')
        attempt_started_at = timestamp()
        def finish_timing():
            elapsed = time.monotonic() - started
            report.update(finished_at=timestamp(), attempt_seconds=elapsed, seconds=previous_seconds + elapsed)
            report.setdefault('attempts', []).append(dict(started_at=attempt_started_at,
                finished_at=report['finished_at'], seconds=elapsed, status=report['status']))
        resources = Resources(getattr(self, 'resource_directory', None))
        def execute(phase):
            try:
                from dataclasses import replace
                from .workflows import ancestors
                if phase.effect in EXTERNAL:
                    artifacts=[artifact for name in ancestors(plan,phase.id) for artifact in rows[name].get('artifacts',[])]
                    phase=replace(phase,environment=dict(phase.environment,
                        BUILD_MANAGER_APPROVED_PLAN=plan.identity,BUILD_MANAGER_APPROVED_ARTIFACTS=json.dumps(artifacts),
                        BUILD_MANAGER_OPERATION_ID=rows[phase.id]['operation_id']))
                with resources.acquire(phase.resources, plan.capacities, cancelled=self.cancelled,
                        timeout=phase.timeout, event=lambda value:self.event(dict(value, phase=phase.id)), cleanup=phase.always):
                    return self.run_phase(phase, output, plan.secret_environment)
            except (OSError, ValueError, RuntimeError) as error:
                return dict(id=phase.id,required=phase.required,status='cancelled' if self.cancelled.is_set() else 'failed',
                            error=Redactor()(str(error)),seconds=0)
        try:
            with ExitStack() as locks:
                from .retention import lease
                locks.enter_context(workspace_lock(output/'supervisor.lock'))
                locks.enter_context(lease(output))
                locks.enter_context(lease(plan.workspace))
                locks.enter_context(workspace_lock(Path(plan.workspace) / 'operation.lock'))
                locks.enter_context(resources.acquire(plan.resources,plan.capacities,cancelled=self.cancelled,
                    timeout=max(phase.timeout for phase in plan.phases),
                    event=lambda value:self.event(dict(value,phase='workflow'))))
                for resource in sorted(set(plan.resource_locks)):
                    locks.enter_context(workspace_lock(resource))
                previous = recover(plan,report,reconcile=reconcile) if resume else []
                rows = {row['id']:row for row in previous if row['status']=='passed'}
                report['status'] = 'running'
                report['phases'] = list(rows.values())
                report['attempt_started_at'] = attempt_started_at
                save()
                pending = [phase for phase in plan.phases if phase.id not in rows]
                running = {}
                with ThreadPoolExecutor(max_workers=plan.max_workers) as pool:
                    while pending or running:
                        changed = False
                        for phase in list(pending):
                            if len(running)>=plan.max_workers:break
                            if any(name not in rows or rows[name]['status']=='running' for name in (*phase.dependencies, *phase.waits_for)):continue
                            if phase.always and running and not phase.dependencies and not phase.waits_for:continue
                            if phase.always and not phase.dependencies and not phase.waits_for and plan.max_workers>1 and any(not p.always for p in pending):continue
                            blocked = any(rows[name]['status']!='passed' for name in phase.dependencies)
                            row = None
                            effect = phase.effect if phase.effect!='inherit' else plan.effect
                            if (self.cancelled.is_set() or blocked) and not phase.always:
                                row = dict(id=phase.id,required=phase.required,status='skipped',
                                           reason='cancelled' if self.cancelled.is_set() else 'dependency did not pass',seconds=0)
                            elif not phase.always:
                                try:
                                    for dependency in phase.dependencies:verify_artifacts(rows[dependency])
                                    if phase.effect in EXTERNAL:
                                        identity = review_identity(plan,phase.id,list(rows.values()))
                                        if not any(a.step==phase.id and a.identity==identity for a in approvals):
                                            row = dict(id=phase.id,required=phase.required,status='awaiting_review',
                                                       reason='Review exact retained artifacts and destination before this effect.',seconds=0)
                                except (OSError,ValueError) as error:
                                    row = dict(id=phase.id,required=phase.required,status='failed',error=str(error),seconds=0)
                            pending.remove(phase);changed=True
                            if row is not None:
                                rows[phase.id]=row;self.event(dict(type='phase',**row))
                            else:
                                rows[phase.id]=dict(id=phase.id,required=phase.required,status='running',effect=effect,operation_id=str(uuid4()))
                                report['phases']=[rows[p.id] for p in plan.phases if p.id in rows]
                                save() # Persist intent before any child or remote request can start.
                                running[pool.submit(execute,phase)]=(phase,effect)
                            report['phases']=[rows[p.id] for p in plan.phases if p.id in rows]
                            save()
                        if running:
                            done,_=wait(running,timeout=.05,return_when=FIRST_COMPLETED)
                            for future in done:
                                phase,effect=running.pop(future);row=future.result()
                                row['operation_id']=rows[phase.id]['operation_id']
                                row['effect']=effect
                                if effect in EXTERNAL and row['status']!='passed':row['status']='unknown'
                                rows[phase.id]=row;self.event(dict(type='phase',**row));changed=True
                        if not changed and not running and pending:
                            raise RuntimeError('Workflow dependencies cannot make progress.')
                        if changed:
                            report['phases']=[rows[p.id] for p in plan.phases if p.id in rows]
                            save()
                statuses=[row['status'] for row in report['phases'] if row['required']]
                cleanup_failed=any(p.always and p.required and rows[p.id]['status']!='passed' for p in plan.phases)
                report['status']=('unknown' if 'unknown' in statuses else 'failed' if cleanup_failed else
                    'awaiting_review' if 'awaiting_review' in statuses else 'cancelled' if self.cancelled.is_set() else
                    'failed' if any(status!='passed' for status in statuses) else 'passed')
                from .retention import durable_hold
                owner = str(output.resolve())
                if report['status'] in {'awaiting_review','unknown'}:
                    paths = {str(Path(plan.workspace)), str(output)}
                    paths.update(str(Path(value).parent) for phase in plan.phases for value in phase.artifacts if Path(value).exists())
                    paths.update(str(Path(value).with_suffix('')) for value in plan.resource_locks if Path(value).with_suffix('').is_dir())
                    report['holds'] = sorted(set(report.get('holds', ())) | paths)
                    for path in report['holds']:durable_hold(path,owner)
                else:
                    for path in report.get('holds', ()):durable_hold(path,owner,release=True)
                    report['holds'] = []
                finish_timing()
                save()
        except (OSError, ValueError, RuntimeError) as error:
            uncertain=any(row.get('status') in {'unknown','running'} and row.get('effect') in EXTERNAL for row in report['phases'])
            report.update(status='unknown' if uncertain else 'cancelled' if self.cancelled.is_set() else 'failed', error=Redactor()(str(error)))
            finish_timing()
            save()
        self.event(dict(type='finished', status=report['status'], seconds=report['seconds']))
        return report

    def run_phase(self, phase, output, secret_environment):
        row = dict(id=phase.id, required=phase.required, kind=phase.kind,
                   started_at=timestamp(), status='running', log=phase.id + '.log')
        self.event(dict(type='phase', **row))
        started = time.monotonic()
        environment = dict(os.environ, **phase.environment)
        redact = Redactor(environment.get(name) for name in secret_environment)
        messages = Queue(maxsize=128)
        process = None
        reader = None
        tail = []
        try:
            if os.name == 'nt':
                from .windows_process import WindowsProcess
                process = WindowsProcess(list(phase.argv), cwd=phase.cwd, env=environment)
            else:
                process = subprocess.Popen(list(phase.argv), cwd=phase.cwd, env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            def read():
                try:
                    while chunk := process.stdout.readline(16384):
                        messages.put(chunk)
                finally:
                    messages.put(None)
            reader = Thread(target=read, daemon=True)
            reader.start()
            finished = False
            # Preserve the child's CRLF rather than translating it a second
            # time on Windows (which would produce CRCRLF/blank log lines).
            with (output / row['log']).open('w', encoding='utf-8', newline='') as stream:
                while not finished or process.poll() is None:
                    if self.cancelled.is_set() and not phase.always:
                        row['status'] = 'cancelled'
                        stop_process(process, grace=phase.stop_grace)
                    elif time.monotonic() - started >= phase.timeout:
                        row['status'] = 'timeout'
                        stop_process(process, grace=phase.stop_grace)
                    if finished:
                        time.sleep(.05)
                        continue
                    try:
                        message = messages.get(timeout=.05)
                    except Empty:
                        continue
                    if message is None:
                        finished = True
                        continue
                    line = redact(message.decode('utf-8', errors='replace'))
                    stream.write(line)
                    stream.flush()
                    tail = (tail + line.splitlines())[-6:]
                    self.event(dict(type='output', phase=phase.id, text=line))
            reader.join(timeout=5)
            process.wait(timeout=5)
            row['exit_code'] = process.returncode
            if row['status'] == 'running':
                row['status'] = 'passed' if process.returncode == 0 else 'failed'
            if phase.artifacts and row['status'] in {'passed', 'failed'}:
                row['artifacts'] = []
                directory = output / 'artifacts'
                directory.mkdir(exist_ok=True)
                for index, value in enumerate(phase.artifacts):
                    source = Path(value)
                    if not source.is_file():
                        if row['status'] != 'passed':
                            continue
                        raise RuntimeError('Expected prepared artifact/report is missing: ' + source.name)
                    # Failed commands retain test reports, not potentially incomplete
                    # deployment artifacts that could be mistaken for prepared output.
                    kind = phase.artifact_types.get(value, 'file')
                    if row['status'] != 'passed' and kind != 'junit':
                        continue
                    destination = directory / f'{phase.id}-{index}{source.suffix}'
                    shutil.copyfile(source, destination)
                    row['artifacts'].append(dict(path=str(destination), original_path=str(source.resolve()), kind=phase.artifact_types.get(value, 'file'),
                                                   sha256=file_sha256(destination, cancelled=self.cancelled.is_set if not phase.always else lambda: False)))
                    if kind == 'junit':
                        from .test_results import read_junit
                        cases = read_junit(destination)
                        for case in cases:
                            case.update({key: Redactor(environment.get(name) for name in secret_environment)(case[key])
                                         for key in ('name', 'classname', 'suite', 'message')})
                        row.setdefault('tests', []).extend(cases)
                        if any(case['status'] in {'failed', 'error'} for case in cases):
                            row.update(status='failed', error='JUnit report contains failing tests.')
        except OperationCancelled as error:
            row.update(status='cancelled', error=redact(str(error)))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            row.update(status='failed', error=redact(str(error)))
        finally:
            if process is not None:
                try:
                    stop_process(process, grace=phase.stop_grace)
                except (OSError, subprocess.SubprocessError) as error:
                    row.update(status='failed', cleanup_error=redact(str(error)))
                # Never block closing a pipe while its reader still holds it.
                # A persistent OS cleanup error remains an explicit failed phase.
                if reader is None or not reader.is_alive():
                    process.stdout.close()
                if os.name == 'nt':
                    process.close()
        row.update(seconds=time.monotonic() - started, finished_at=timestamp())
        if row['status'] != 'passed':
            row['summary'] = '\n'.join(tail)
        return row
