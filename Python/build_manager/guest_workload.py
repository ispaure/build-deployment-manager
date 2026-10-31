"""Reusable guest workload lifecycle over the existing ownership-checked transports.

Source membership, dependency recipes and plans are supplied by the project.
Transport admission/reconciliation remains in Parallels and WindowsGuest.
"""
import io
import json
from pathlib import Path, PureWindowsPath
import subprocess
import time
import zipfile
from uuid import uuid4

from .profiles import save_json

ERRORS = (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError)


class GuestResultLifecycle:
    """Persist intent, retrieve evidence before cleanup, and retain uncertain work."""
    def __init__(self, result, directory, backend, workspace_key, *, expected_plan=None):
        self.result, self.directory = result, Path(directory)
        if result.get('backend', backend) != backend:
            raise ValueError('Guest result backend differs from its lifecycle owner.')
        result['backend'] = backend
        self.backend, self.workspace_key = backend, workspace_key
        self.started = time.monotonic()
        self.collected = False
        self.expected_plan = expected_plan
        save_json(self.directory / 'result.json', self.result)

    def collect(self, collect, evidence, cleanup):
        try:
            collect()
            self.collected = True
            evidence = Path(evidence)
            if evidence.is_file():
                report = json.loads(evidence.read_text())
                if not isinstance(report, dict):
                    raise ValueError('Guest report must be an object.')
                if report['source'] != self.result['source'] or report['backend'] != self.backend:
                    raise ValueError('Retrieved guest report belongs to different source/backend.')
                if self.expected_plan is not None:
                    if report.get('plan_identity') != self.expected_plan.identity:
                        raise ValueError('Retrieved report belongs to a different guest plan.')
                    rows = report.get('phases')
                    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows) or len({row['id'] for row in rows}) != len(rows):
                        raise ValueError('Invalid guest phase evidence.')
                    statuses = {row['id']: row['status'] for row in rows}
                    if report['status'] == 'passed' and any(statuses.get(p.id) != 'passed' for p in self.expected_plan.phases if p.required):
                        raise ValueError('Required guest phase evidence is missing or unsuccessful.')
                self.result['phases'] = report['phases']
                self.result['guest_result'] = str(evidence)
                if self.result['status'] == 'passed' and report['status'] != 'passed':
                    raise ValueError('Guest exit status disagrees with its required test result.')
            elif self.result['status'] == 'passed':
                raise ValueError('A passing guest process did not produce its required result.')
        except Exception as error:
            self.result.update(status='failed', retrieval_error=str(error))
        if self.collected:
            try:
                cleanup()
                self.result[self.workspace_key + '_removed'] = True
            except Exception as error:
                self.result.update(status='failed', cleanup_error=str(error))
        else:
            self.result[self.workspace_key + '_preserved_for_recovery'] = True

    def finish(self):
        self.result['seconds'] = time.monotonic() - self.started
        save_json(self.directory / 'result.json', self.result)
        print(json.dumps(self.result), flush=True)


def waiting_progress(backend, stage):
    def present(event):
        state = 'reconciling worker receipt' if event['state'] == 'reconciling' else 'waiting for worker result'
        print(f"{backend} · {stage} · {state} · {event['seconds']:.0f}s (headless)", flush=True)
    return present


def prepare_windows(client, vm, output, tools, *, python, guest_architecture, python_architecture):
    """Prepare supplied pins once per receipt; retain uncertain setup identity."""
    from .locking import workspace_lock
    output = Path(output)
    with workspace_lock(output.parent / (output.name + '.prepare.lock')):
        return _prepare_windows(client, vm, output, tools, python=python,
            guest_architecture=guest_architecture, python_architecture=python_architecture)


def _prepare_windows(client, vm, output, tools, *, python, guest_architecture, python_architecture):
    from .guest_tools import WINDOWS_PREPARE, windows_parameters
    token = uuid4().hex
    parameters = windows_parameters(token, tools, python=python,
        guest_architecture=guest_architecture, python_architecture=python_architecture)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Preserve the existing guest preparation receipt; choose a fresh output.')
    guest = client.start(vm)
    record = dict(token=token, vm=guest['uuid'], status='preparing', tests_run=False)
    save_json(output, record)
    try:
        prepared = json.loads(client.powershell(guest['uuid'], WINDOWS_PREPARE, parameters, timeout=360))
        if prepared.get('token') != token:
            raise ValueError('Prepared workspace token mismatch.')
        record.update(prepared, status='prepared', original_state=guest['status'])
        return record
    except ERRORS as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        save_json(output, record)


def source_zip(snapshot, members):
    """Encode explicit public members, rejecting links and parent traversal."""
    from .command_project import inventory
    members = tuple(members)
    try:
        files = inventory(snapshot, members, public_only=False)
    except ValueError as error:
        if 'symbolic links' in str(error):
            raise ValueError('Windows source transfer cannot flatten a symbolic link: ' + str(error)) from error
        raise
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        # Git requires even empty metadata directories (for example refs/) to
        # recognize a transferred checkout. Inventory above validates directories
        # as well as files; preserve them instead of flattening to files alone.
        directories = set()
        for name in members:
            path = Path(snapshot) / name
            if path.is_dir():
                directories.update(p for p in (path, *path.rglob('*')) if p.is_dir())
        for path in sorted(directories):
            archive.write(path, path.relative_to(snapshot).as_posix())
        for name, file in sorted(files.items()):
            archive.write(file, name)
    return stream.getvalue()


def execute_plan(*, plan, python, write, execute, plan_path, reports, environment, timeout, cancel_file=None):
    """Shared plan submission; callbacks are bound to one owned guest workspace."""
    write(json.dumps(plan.data(), indent=2).encode())
    argv = [python, '-m', 'build_manager', plan_path, '--output', reports]
    if cancel_file:
        argv.extend(['--cancel-file', cancel_file])
    return execute(argv, environment, timeout)


class LinuxSession:
    """A fresh Linux workspace on an explicitly selected, ready guest account."""
    def __init__(self, client, vm, uid, gid, *, token=None):
        self.client, self.vm, self.uid, self.gid = client, vm, uid, gid
        self.token = token or uuid4().hex
        if len(self.token) != 32 or any(c not in '0123456789abcdef' for c in self.token) or type(uid) is not int or type(gid) is not int or uid < 1000 or gid < 0:
            raise ValueError('Use an owned token and an explicit normal guest account.')
        self.workspace = '/var/tmp/' + self.token
        self.source = self.workspace + '/source'
        self.reports = self.workspace + '/reports'
        self.python = self.workspace + '/environment/bin/python'
        self.plan_path = self.workspace + '/plan.json'
        self.evidence = 'reports/manager/result.json'
        self.staged = False

    def prepare_environment(self, execute, parameters):
        from .guest_tools import LINUX_BOOTSTRAP, linux_parameters
        execute(['python3', '-c', LINUX_BOOTSTRAP, self.workspace,
                 json.dumps(linux_parameters(**parameters))], {}, 1020)

    def stage(self, snapshot, members):
        self.client.stage(self.vm, snapshot, self.workspace, self.token, self.uid, self.gid, members=members)
        self.staged = True

    def exists(self):
        return self.staged or self.client.owned_exists(self.vm, self.workspace, self.token)

    def execute(self, argv, environment, cancelled, timeout):
        return self.client.run_owned(self.vm, self.workspace, self.token, self.uid, argv, environment, cancelled,
            timeout=timeout, progress=waiting_progress('Linux', 'guest command'))

    def write(self, data):
        self.client.write_owned(self.vm, self.workspace, self.token, 'plan.json', data, self.uid, self.gid)

    def collect(self, destination):
        self.client.collect(self.vm, self.workspace, self.token, destination)

    def cleanup(self):
        self.client.remove(self.vm, self.workspace, self.token)


class WindowsSession:
    """One operation beneath prepared owned tools; dependencies use a fresh venv.

    prepare_windows handles the base tool cache. The project supplies a venv
    creation/setup recipe using this session's distinct python path.
    """
    def __init__(self, client, prepared, *, operation=None):
        from .windows_guest import WindowsGuest
        if prepared.get('status') != 'prepared':
            raise ValueError('A verified prepared Windows tool receipt is required.')
        self.operation = operation or uuid4().hex
        if len(self.operation) != 32 or any(c not in '0123456789abcdef' for c in self.operation):
            raise ValueError('Invalid Windows operation identity.')
        self.vm, self.token, self.workspace = prepared['vm'], prepared['token'], prepared['workspace']
        root = PureWindowsPath(self.workspace)
        base = PureWindowsPath(prepared['python'])
        if (not isinstance(self.token, str) or len(self.token) != 32
                or any(c not in '0123456789abcdef' for c in self.token)
                or not root.is_absolute() or root.name != self.token or '..' in root.parts
                or not base.is_relative_to(root) or '..' in base.parts):
            raise ValueError('Prepared Windows paths must belong to the token-owned workspace.')
        self.guest = WindowsGuest(client, self.vm, self.workspace, self.token, self.operation)
        self.source_name, self.reports_name = 'source-' + self.operation, 'reports-' + self.operation
        self.environment_name = 'environment-' + self.operation
        root = PureWindowsPath(self.workspace)
        self.source, self.reports = str(root / self.source_name), str(root / self.reports_name)
        self.python = str(root / self.environment_name / 'Scripts/python.exe')
        self.base_python = prepared['python']
        self.plan_name = 'plan-' + self.operation + '.json'
        self.plan_path = str(root / self.plan_name)
        self.cancel_file = str(root / ('cancel-' + self.operation))
        self.evidence = self.reports_name + '/manager/result.json'
        self.attempted = False

    def prepare_environment(self, execute, parameters):
        if parameters:
            raise ValueError('Windows runtime is selected by its prepared tool receipt.')
        execute([self.base_python, '-m', 'venv', str(PureWindowsPath(self.workspace) / self.environment_name)], {}, 300)

    def stage(self, snapshot, members):
        payload = source_zip(snapshot, members)
        self.attempted = True
        self.guest.stage(self.source_name, payload)

    def exists(self):
        return self.attempted  # Collection reconciles uncertain staging; never replay commands.

    def execute(self, argv, environment, cancelled, timeout):
        return self.guest.run(argv[0], argv[1:], self.source_name, self.reports_name,
            environment, cancelled, timeout=timeout, progress=waiting_progress('Windows', 'guest command'))

    def write(self, data):
        self.guest.write(self.plan_name, data)

    def collect(self, destination):
        self.guest.collect([self.reports_name], destination)

    def cleanup(self):
        self.guest.remove_paths([self.source_name, self.source_name + '.zip', self.reports_name,
            self.environment_name, self.plan_name, 'operation-' + self.operation,
            'cancel-' + self.operation, 'evidence-' + self.operation + '.zip'])


def run_workload(session, *, snapshot, members, directory, source, backend, prepare, make_plan,
                 environment, cancelled, toolchain=None, timeout=3600):
    """Stage → project setup → validated plan → run → collect → cleanup.

    prepare(session, execute) supplies dependency policy. make_plan(session)
    supplies an ordinary Plan. execute(argv, env, seconds) supervises every guest
    setup command. Callers retain snapshot ownership, result retention and VM power
    policy. Never retries an uncertain workload or removes uncollected evidence.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    result = dict(schema=1, status='running', source=source, backend=backend, vm=session.vm,
                  workspace=session.workspace, workspace_token=session.token, phases=[])
    cleanup_key = 'guest_operation' if isinstance(session, WindowsSession) else 'guest_workspace'
    if isinstance(session, WindowsSession):
        result.update(operation=session.operation, public_tool_workspace_retained=True)
    lifecycle = GuestResultLifecycle(result, directory, backend, cleanup_key)
    attempted = False
    def execute(argv, env, seconds):
        if cancelled.is_set():
            raise ValueError('Guest workload cancelled.')
        code = session.execute(argv, env, cancelled, seconds)
        if code:
            raise RuntimeError('Guest command failed with exit code ' + str(code))
        return code
    try:
        if cancelled.is_set():
            result['status'] = 'cancelled'
        else:
            attempted = True
            session.stage(snapshot, members)
            session.prepare_environment(execute, toolchain or {})
            prepare(session, execute)
            plan = make_plan(session)
            if plan.source != source or plan.backend != backend:
                raise ValueError('Guest plan source/backend does not match captured workload.')
            lifecycle.expected_plan = plan
            execute_plan(plan=plan, python=session.python, write=session.write,
                execute=execute, plan_path=session.plan_path, reports=session.reports + ('\\manager' if isinstance(session, WindowsSession) else '/manager'),
                environment=environment, timeout=timeout, cancel_file=getattr(session, 'cancel_file', None))
            result['status'] = 'cancelled' if cancelled.is_set() else 'passed'
    except Exception as error:
        result.update(status='cancelled' if cancelled.is_set() else 'failed', error=str(error))
    finally:
        if attempted:
            try:
                if session.exists():
                    lifecycle.collect(lambda: session.collect(directory / 'guest'),
                        directory / 'guest' / session.evidence, session.cleanup)
                elif result['status'] == 'passed':
                    result.update(status='failed', retrieval_error='Owned workspace disappeared before collection.')
            except Exception as error:
                result.update(status='failed', cleanup_check_error=str(error))
                result[cleanup_key + '_preserved_for_recovery'] = True
        lifecycle.finish()
    return result
