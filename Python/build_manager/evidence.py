"""Authenticated local test receipts; projects declare the complete input identity.

An evidence hit is labelled reuse, never a new execution. Missing, tampered or
expired retained artifacts are cache misses. External effects are never cached.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import time
from contextlib import contextmanager

from .locking import workspace_lock
from .profiles import save_json
from .registry import config_directory
from .workflows import verify_artifacts


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class EvidenceCache:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else config_directory() / 'test-evidence'

    def key(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / 'authentication.key'
        with workspace_lock(self.directory / 'authentication.lock', timeout=5):
            if not path.exists():
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(secrets.token_bytes(32))
            if not path.is_file() or path.is_symlink() or os.name != 'nt' and path.stat().st_mode & 0o077:
                raise ValueError('Evidence authentication key must be a private regular file.')
            value = path.read_bytes()
            if len(value) != 32:
                raise ValueError('Invalid evidence authentication key.')
            return value

    @contextmanager
    def locked(self, path, cancelled):
        from contextlib import ExitStack
        with ExitStack() as stack:
            while not cancelled():
                try:
                    stack.enter_context(workspace_lock(path))
                    break
                except RuntimeError:
                    time.sleep(.05)
            yield not cancelled()

    def read(self, phase, key):
        path = self.directory / (phase.reuse_key + '.json')
        try:
            if path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
                return None
            receipt = json.loads(path.read_bytes())
            payload = receipt['payload']
            signature = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, receipt['signature']):
                return None
            if payload['schema'] != 1 or payload['reuse_key'] != phase.reuse_key:
                return None
            row = payload['row']
            if row['status'] != 'passed' or len(row.get('artifacts', [])) != len(phase.artifacts):
                return None
            verify_artifacts(row)
            return payload
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def execute(self, phase, output, action, *, cancelled=lambda: False):
        if not phase.reuse_key:
            return action()
        key = self.key()
        with self.locked(self.directory / (phase.reuse_key + '.lock'), cancelled) as acquired:
            if not acquired:
                return action()
            receipt = self.read(phase, key)
            if receipt is not None:
                old = receipt['row']
                destinations = [Path(path) for path in phase.artifacts]
                # Never overwrite an existing owner output with different bytes.
                from commonUtils.runtime.streams import file_sha256
                compatible = all(not path.exists() or path.is_file() and
                    file_sha256(path) == artifact['sha256']
                    for path, artifact in zip(destinations, old.get('artifacts', [])))
                if compatible:
                    artifacts = []
                    for index, (path, original) in enumerate(zip(destinations, old.get('artifacts', []))):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if not path.exists():
                            shutil.copyfile(original['path'], path)
                        retained = Path(output) / 'artifacts' / (phase.id + '-' + str(index) + path.suffix)
                        retained.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, retained)
                        artifacts.append(dict(original, path=str(retained), original_path=str(path)))
                    row = dict(old, id=phase.id, required=phase.required, seconds=0,
                               artifacts=artifacts, reused=True,
                               reuse=dict(key=phase.reuse_key, output=receipt['output'],
                                          step=old['id'], original_seconds=old.get('seconds'),
                                          started_at=old.get('started_at'), finished_at=old.get('finished_at')))
                    from datetime import datetime, timezone
                    row['started_at'] = row['finished_at'] = datetime.now(timezone.utc).isoformat()
                    row.pop('operation_id', None)
                    row.pop('current_test', None)
                    row['log'] = phase.id + '.log'
                    (Path(output) / row['log']).write_text('Reused authenticated test evidence from '
                        + receipt['output'] + ' / ' + old['id'] + '\n')
                    return row
            row = action()
            if row['status'] == 'passed':
                verify_artifacts(row)
                payload = dict(schema=1, reuse_key=phase.reuse_key, output=str(Path(output).resolve()), row=row)
                save_json(self.directory / (phase.reuse_key + '.json'), dict(payload=payload,
                    signature=hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()))
            return row
