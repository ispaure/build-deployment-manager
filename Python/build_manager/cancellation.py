"""Run-local cooperative requests; no process signals or result-report writes."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from commonUtils.persistence.locking import file_lock
from .profiles import save_json
from .retention import linked

CAPABILITY = 'cancel-capability.json'
LOCK = 'cancel-control.lock'
LIMIT = 16384


def checked_root(output):
    path = Path(output).absolute()
    if linked(path) or not path.is_dir():
        raise ValueError('Cancellation requires an existing unlinked run directory.')
    # Normalize system aliases such as macOS /var; bind the final directory inode.
    return path.resolve()


def request_path(root, attempt):
    if not isinstance(attempt, str) or not re.fullmatch('[0-9a-f]{32}', attempt):
        raise ValueError('Invalid cancellation attempt nonce.')
    return root / ('cancel-request-' + attempt + '.json')


def checked_file(path, *, missing=False):
    if linked(path):
        raise ValueError('Cancellation refuses linked control/evidence files.')
    try:
        value = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if missing:
            return
        raise
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('Cancellation requires regular, unshared control/evidence files.')


def read_control(path):
    checked_file(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        value = os.fstat(stream.fileno())
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise ValueError('Invalid cancellation record.')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Cancellation record exceeds its bounded size.')
    try:
        result = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ValueError('Invalid cancellation record.') from error
    if not isinstance(result, dict):
        raise ValueError('Invalid cancellation record.')
    return result


def digest(engine):
    return hashlib.sha256(json.dumps(engine, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def root_identity(root):
    value = root.stat()
    return [value.st_dev, value.st_ino]


def require_capability(root):
    try:
        value = read_control(root / CAPABILITY)
    except FileNotFoundError as error:
        raise ValueError('No cancellation capability: this run is not yet admitted, has ended, or uses an older SDK. Use its original controller Stop/interrupt and inspect status.') from error
    if (type(value.get('schema')) is not int or value['schema'] != 1 or value.get('root') != root_identity(root)
            or not re.fullmatch('[0-9a-f]{32}', str(value.get('attempt', '')))
            or any(not re.fullmatch('[0-9a-f]{64}', str(value.get(key, '')))
                   for key in ('identity', 'engine'))):
        raise ValueError('Unrecognized cancellation capability; use the original controller.')
    return value


def require_live(root):
    path = root / LOCK
    checked_file(path)
    with file_lock(path, timeout=0) as acquired:
        if acquired:
            raise ValueError('This attempt is no longer cancellable; inspect its retained status. No process was signalled.')


@contextmanager
def cancellable_attempt(output, identity, engine, cancelled):
    """Advertise only after admission; the original scheduler owns consumption."""
    root = checked_root(output)
    for name in (LOCK, CAPABILITY):
        checked_file(root / name, missing=True)
    with file_lock(root / LOCK, timeout=0) as acquired:
        if not acquired:
            raise RuntimeError('Another cancellation controller owns this run.')
        value = dict(schema=1, root=root_identity(root), identity=identity,
                     attempt=uuid4().hex, engine=digest(engine))
        own_request = request_path(root, value['attempt'])
        checked_file(own_request, missing=True)
        save_json(root / CAPABILITY, value)
        def poll():
            try:
                if linked(root) or root_identity(root) != value['root']:
                    return
                request = read_control(own_request)
            except (OSError, ValueError):
                return  # Malformed/old requests cannot change execution outcomes.
            if request == value:
                cancelled.set()
        yield poll
    # The immutable capability is historical evidence, never proof of liveness.
    # Releasing its separate lock makes late requests fail, including after crash.


def request_cancellation(output, *, expected_identity, confirmed=False, expected_attempt=None):
    """Return requested, never finished. A resumed attempt requires a new request."""
    if confirmed is not True:
        raise ValueError('Cancellation requires explicit confirmation.')
    if not isinstance(expected_identity, str) or not re.fullmatch('[0-9a-f]{64}', expected_identity):
        raise ValueError('Supply the reviewed plan SHA256 with --expect-identity.')
    root = checked_root(output)
    value = require_capability(root)
    if value['identity'] != expected_identity:
        raise ValueError('Cancellation plan identity does not match this run.')
    if expected_attempt is not None and value['attempt'] != expected_attempt:
        raise ValueError('Cancellation attempt changed; inspect the current controller before requesting again.')
    checked_file(root / 'plan.json')
    checked_file(root / 'result.json')
    from .history import load_run
    plan, report = load_run(root / 'result.json')
    if (plan.identity != expected_identity or digest(report.get('engine')) != value['engine']
            or report['status'] not in {'running', 'queued'}):
        raise ValueError('Saved run/engine is not this active cancellable attempt; inspect status.')
    require_live(root)
    own_request = request_path(root, value['attempt'])
    checked_file(own_request, missing=True)
    if require_capability(root) != value:
        raise ValueError('Cancellation attempt changed before request; inspect status.')
    save_json(own_request, value)
    if require_capability(root) != value:
        raise ValueError('Cancellation raced an attempt change; inspect status. The new attempt will ignore this request.')
    require_live(root)
    return dict(status='requested', identity=expected_identity, attempt=value['attempt'],
                message='Cancellation requested; the original controller still owns cleanup. Inspect status for completion.')
