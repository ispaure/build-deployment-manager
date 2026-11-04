"""Bounded protocol transport whose process group/job outlives every request."""
import json
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import time

from .executor import stop_process

STOP_GRACE = 15  # Project SIGTERM cleanup/lease holding is bounded to ten seconds.
DRAIN_TIMEOUT = 3


def session_groups(session):
    """Read only PID/group/state metadata; never discover commands or signal outsiders."""
    ps = next((path for path in ('/bin/ps', '/usr/bin/ps') if Path(path).is_file()), None)
    if ps is None:
        raise OSError('Owned session inventory is unavailable.')
    result = subprocess.run([ps, '-A', '-o', 'pid=,pgid=,stat='], capture_output=True, text=True, timeout=1)
    if result.returncode:
        raise OSError('Owned session inventory is unavailable.')
    groups = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise OSError('Owned session inventory is invalid.')
        try:
            pid, group = map(int, fields[:2])
        except ValueError as error:
            raise OSError('Owned session inventory is invalid.') from error
        try:
            owned = os.getsid(pid) == session
        except (ProcessLookupError, PermissionError):
            continue
        # Zombies cannot mutate or retain pipe writers; their original parent
        # owns reaping. The bridge itself is reaped through its Popen handle.
        if owned and not fields[2].startswith(('Z', 'X')):
            groups.setdefault(group, []).append(pid)
    return groups


def signal_session(session, groups, sig):
    for group, members in groups.items():
        if group <= 0:
            raise OSError('Invalid owned process group.')
        for pid in members:
            try:
                if os.getsid(pid) == session and os.getpgid(pid) == group:
                    os.killpg(group, sig)
                    break
            except ProcessLookupError:
                continue


def teardown_receipt(process, stage, error, groups, *, session_verified_empty=False):
    """Bounded owned-process metadata only; exception text may contain secrets."""
    pid = getattr(process, 'pid', None)
    pid = pid if type(pid) is int else None
    members = [dict(pid=member, pgid=group) for group, values in groups.items() for member in values]
    code = process.returncode if type(process.returncode) is int else None
    return dict(schema=1, bridge_pid=pid, session_id=pid, stage=stage,
                error_class=type(error).__name__, root_exit_code=code,
                last_verified_owned_processes=members[:32], owned_process_count=len(members),
                truncated=len(members) > 32, session_verified_empty=session_verified_empty,
                ownership='incomplete', retry_safe=False)


def teardown_failure(process, stage, error, *, session_verified_empty=False):
    receipt = getattr(error, '_owned_bridge_receipt', None)
    if receipt is None:
        receipt = teardown_receipt(process, stage, error, {}, session_verified_empty=session_verified_empty)
    failure = ValueError('Owned project bridge teardown failed; do not assume the operation stopped. '
                        'Preserve this owned-session receipt for inspection; do not repeat the request: '
                        + json.dumps(receipt, sort_keys=True))
    failure.receipt = receipt
    return failure


def stop_session(process):
    """Retire every subgroup in the session created for this exact bridge."""
    deadline = time.monotonic() + STOP_GRACE
    signalled = set()
    groups = {}
    stage = 'session_inventory'
    try:
        while True:
            stage = 'root_poll'
            process.poll()
            stage = 'session_inventory'
            groups = session_groups(process.pid)
            if not groups:
                break
            stage = 'session_sigterm'
            signal_session(process.pid, {key: value for key, value in groups.items() if key not in signalled}, signal.SIGTERM)
            signalled.update(groups)
            if time.monotonic() >= deadline:
                deadline = time.monotonic() + 5
                while groups:
                    stage = 'session_sigkill'
                    signal_session(process.pid, groups, signal.SIGKILL)
                    if time.monotonic() >= deadline:
                        stage = 'session_verify_exit'
                        raise subprocess.TimeoutExpired(process.args, STOP_GRACE + 5)
                    time.sleep(.02)
                    stage = 'root_poll'
                    process.poll()
                    stage = 'session_inventory'
                    groups = session_groups(process.pid)
                break
            time.sleep(.02)
        stage = 'root_reap'
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        # Inventory failure cannot become a successful cancellation. Still stop
        # the known root group and give project cleanup its full lease window.
        receipt = teardown_receipt(process, stage, error, groups,
                                   session_verified_empty=stage == 'root_reap' and not groups)
        try:
            stop_process(process, grace=STOP_GRACE)
        except (OSError, subprocess.SubprocessError) as fallback_error:
            receipt['fallback_error_class'] = type(fallback_error).__name__
        error._owned_bridge_receipt = receipt
        raise


def check_request(cancelled, deadline):
    if cancelled():
        raise ValueError('Project request cancelled.')
    if time.monotonic() >= deadline:
        raise ValueError('Project request timed out. Check the project interpreter and adapter.')


def run(argv, payload, *, cwd, env, timeout, cancelled):
    if os.name == 'nt':
        return run_windows(argv, payload, cwd=cwd, env=env, timeout=timeout, cancelled=cancelled)
    try:
        session_groups(os.getsid(0))
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('Cannot start project bridge: host process inventory is unavailable. '
                         'Install or repair the host ps utility before running project actions.') from error
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while True:
            check_request(cancelled, deadline)
            try:
                stdout, stderr = process.communicate(payload, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                payload = None
                if process.poll() is not None:
                    break  # Descendant-held pipes must not conceal an exited bridge.
    finally:
        session_verified_empty = False
        stage = 'session_teardown'
        try:
            stop_session(process)
            session_verified_empty = True
            stage = 'pipe_drain'
            stdout, stderr = process.communicate(timeout=DRAIN_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as error:
            raise teardown_failure(process, stage, error, session_verified_empty=session_verified_empty) from error
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


# WindowsProcess owns a suspended child before its first thread runs, but its
# phase transport intentionally has NUL stdin and merged output. This stdlib-only
# envelope preserves the adapter protocol through private files inside that job.
WINDOWS_ENVELOPE = '''import json,subprocess,sys
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
with open(request['stdin'],'rb') as source, open(request['stdout'],'wb') as output, open(request['stderr'],'wb') as errors:
    child=subprocess.Popen(request['argv'],stdin=source,stdout=output,stderr=errors)
    code=child.wait()
raise SystemExit(code)
'''


def run_windows(argv, payload, *, cwd, env, timeout, cancelled):
    from .windows_process import WindowsProcess
    with TemporaryDirectory(prefix='manager-bridge-') as temporary:
        directory = Path(temporary)
        request = dict(argv=list(argv), **{key: str(directory / (key + '.txt'))
                                          for key in ('stdin', 'stdout', 'stderr')})
        Path(request['stdin']).write_text(payload, encoding='utf-8')
        envelope = directory / 'request.json'
        envelope.write_text(json.dumps(request), encoding='utf-8')
        process = WindowsProcess([argv[0], '-I', '-B', '-c', WINDOWS_ENVELOPE, str(envelope)], cwd=cwd, env=env)
        # Drain the envelope diagnostics independently; project stdout/stderr are
        # separate files and cannot be kept open by an unowned reader thread.
        envelope_tail, drain_errors = bytearray(), []
        def drain():
            try:
                while chunk := process.stdout.read(16384):
                    envelope_tail.extend(chunk)
                    del envelope_tail[:-8192]
            except OSError as error:
                drain_errors.append(error)
        reader = Thread(target=drain, name='project-bridge-envelope', daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_request(cancelled, deadline)
                time.sleep(.05)
            code = process.returncode
        finally:
            try:
                stop_process(process, grace=STOP_GRACE)
                process.wait_tree(timeout=5)
                reader.join(timeout=DRAIN_TIMEOUT)
                if reader.is_alive():
                    raise ValueError('Owned project bridge output did not drain.')
                if drain_errors:
                    raise ValueError('Owned project bridge output could not be drained.')
            except (OSError, subprocess.SubprocessError) as error:
                raise ValueError('Owned project bridge teardown failed; do not assume the operation stopped.') from error
            finally:
                if not reader.is_alive():
                    process.stdout.close()
                process.close()
        stdout = Path(request['stdout']).read_text(encoding='utf-8', errors='replace') if Path(request['stdout']).is_file() else ''
        stderr = Path(request['stderr']).read_text(encoding='utf-8', errors='replace') if Path(request['stderr']).is_file() else ''
        if not stderr and code:
            stderr = bytes(envelope_tail).decode('utf-8', errors='replace')
        return subprocess.CompletedProcess(argv, code, stdout, stderr)
