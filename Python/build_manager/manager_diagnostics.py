"""Private, bounded GUI diagnostics; never reads or writes execution evidence."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
from uuid import uuid4

from commonUtils.persistence.locking import file_lock
from .diagnostics import bounded
from .profiles import save_json
from .redaction import ShareRedactor

MAX_RECORDS = 32
MAX_RECORD_BYTES = 65536


class DiagnosticUnavailable(ValueError):
    pass


class DiagnosticStore:
    """32 fixed slots bound discovery, total bytes and stable lease-file growth."""
    def __init__(self, registry_directory):
        self.registry_directory = Path(registry_directory)
        self.root = self.registry_directory / 'diagnostics'
        self.warning = ''

    def _directory(self):
        if self.registry_directory.is_symlink() or self.root.is_symlink() or self.root.exists() and not self.root.is_dir():
            raise DiagnosticUnavailable('Manager diagnostic storage is not a regular directory.')
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            raise DiagnosticUnavailable('Manager diagnostic recording is unavailable.') from error

    def _path(self, slot, suffix='json'):
        return self.root / f'{slot:02d}.{suffix}'

    @staticmethod
    def _regular(path, *, missing=True):
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing:
                return False
            raise DiagnosticUnavailable('Manager diagnostic is unavailable.')
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DiagnosticUnavailable('Linked or non-file manager diagnostics are unavailable.')
        return True

    @contextmanager
    def _lock(self):
        self._directory()
        path = self.root / 'admission.lock'
        self._regular(path)
        try:
            with file_lock(path, timeout=.2) as acquired:
                if not acquired:
                    raise DiagnosticUnavailable('Manager diagnostic storage is busy.')
                yield
        except OSError as error:
            raise DiagnosticUnavailable('Manager diagnostic recording is unavailable.') from error

    def _lease(self, slot):
        path = self._path(slot, 'lock')
        self._regular(path)
        return file_lock(path)

    def _read(self, slot):
        path = self._path(slot)
        self._regular(path, missing=False)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise DiagnosticUnavailable('Manager diagnostic is not a regular file.')
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise DiagnosticUnavailable('Manager diagnostic exceeds its size limit.')
            row = json.loads(raw)
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            raise DiagnosticUnavailable('Manager diagnostic cannot be read.') from error
        if (not isinstance(row, dict) or type(row.get('schema')) is not int or row.get('schema') != 1 or row.get('kind') != 'manager-diagnostic'
                or set(row) != {'schema', 'kind', 'id', 'state', 'started_at', 'message', 'exception', 'stack'}
                or not isinstance(row.get('id'), str) or not re.fullmatch(rf'{slot:02d}-[0-9a-f]{{32}}', row['id'])
                or not isinstance(row.get('state'), str) or row['state'] not in {'active', 'error', 'ended'}
                or any(not isinstance(row.get(field, ''), str) for field in ('message', 'exception', 'stack', 'started_at'))):
            raise DiagnosticUnavailable('Manager diagnostic format is invalid.')
        return row

    @staticmethod
    def _slot(identity):
        if not isinstance(identity, str) or not re.fullmatch(r'(?:[0-2][0-9]|3[01])-[0-9a-f]{32}', identity):
            raise DiagnosticUnavailable('Invalid manager diagnostic identity.')
        return int(identity[:2])

    def _write(self, slot, row):
        self._regular(self._path(slot))
        if len((json.dumps(row, indent=2) + '\n').replace('\n', os.linesep).encode()) > MAX_RECORD_BYTES:
            raise DiagnosticUnavailable('Manager diagnostic exceeds its size limit.')
        try:
            save_json(self._path(slot), row)
        except OSError as error:
            raise DiagnosticUnavailable('Manager diagnostic recording is unavailable.') from error

    def start(self):
        with self._lock():
            # A malformed oversized/linked slot must not cause new admission to
            # silently exceed the store's byte or identity boundary.
            for slot in range(MAX_RECORDS):
                path = self._path(slot)
                if self._regular(path) and path.stat().st_size > MAX_RECORD_BYTES:
                    raise DiagnosticUnavailable('Manager diagnostic storage contains an oversized record.')
            for slot in range(MAX_RECORDS):
                if self._path(slot).exists() or self._path(slot).is_symlink():
                    continue
                lease = self._lease(slot)
                if not lease.__enter__():
                    lease.__exit__(None, None, None)
                    continue
                row = dict(schema=1, kind='manager-diagnostic', id=f'{slot:02d}-' + uuid4().hex,
                    state='active', started_at=datetime.now(timezone.utc).isoformat(),
                    message='', exception='', stack='')
                try:
                    self._write(slot, row)
                except BaseException:
                    lease.__exit__(None, None, None)
                    raise
                return DiagnosticSession(self, slot, row, lease)
        raise DiagnosticUnavailable('Manager diagnostic storage is full. Inspect and dismiss a saved report to enable recording.')

    def read(self, identity):
        slot = self._slot(identity)
        with self._lock():
            row = self._read(slot)
            if row['id'] != identity:
                raise DiagnosticUnavailable('Manager diagnostic identity changed.')
            return row

    def pending(self):
        rows = []
        self.warning = ''
        with self._lock():
            for slot in range(MAX_RECORDS):
                if not self._path(slot).exists() and not self._path(slot).is_symlink():
                    continue
                try:
                    with self._lease(slot) as acquired:
                        if not acquired:
                            continue
                        row = self._read(slot)
                        if row['state'] == 'active':
                            row = dict(row, state='ended', message='The previous manager session ended unexpectedly. The cause and run outcomes are unavailable.')
                        rows.append(row)
                except (DiagnosticUnavailable, OSError):
                    self.warning = 'Some manager diagnostics could not be read.'
        return rows

    def dismiss(self, identity):
        slot = self._slot(identity)
        with self._lock():
            with self._lease(slot) as acquired:
                if not acquired:
                    raise DiagnosticUnavailable('This manager session is still active.')
                row = self._read(slot)
                if row['id'] != identity:
                    raise DiagnosticUnavailable('Manager diagnostic identity changed.')
                self._path(slot).unlink()


class DiagnosticSession:
    def __init__(self, store, slot, row, lease):
        self.store, self.slot, self.row, self.lease = store, slot, row, lease
        self.id, self.closed = row['id'], False
        self.warning = ''
        self.previous_hooks = None

    def record_exception(self, exception_type, value, tb):
        if self.closed:
            return
        redact = ShareRedactor()
        # StackSummary source lines can expose arguments. Extract frame metadata only.
        frames = []
        while tb is not None and len(frames) < 80:
            frame = tb.tb_frame
            frames.append(f'File "{frame.f_code.co_filename}", line {tb.tb_lineno}, in {frame.f_code.co_name}')
            tb = tb.tb_next
        try:
            name = bounded(redact.text(exception_type.__name__), 160)
            message = bounded(redact.text(str(value)), 2048)
        except Exception:
            name, message = 'Exception', 'The exception message could not be formatted.'
        self.row.update(state='error', exception=name, message=message,
                        stack=bounded(redact.text('\n'.join(frames)), 8192))
        try:
            with self.store._lock():
                if self.store._read(self.slot)['id'] != self.id:
                    raise DiagnosticUnavailable('Manager diagnostic identity changed.')
                self.store._write(self.slot, self.row)
        except (DiagnosticUnavailable, OSError):
            self.warning = 'Manager error recording is unavailable; existing run evidence is unchanged.'

    def install_hooks(self):
        if self.previous_hooks is not None:
            return
        self.previous_hooks = (sys.excepthook, threading.excepthook)
        previous_exception, previous_thread = self.previous_hooks
        def exception_hook(kind, value, tb):
            try:
                self.record_exception(kind, value, tb)
            finally:
                previous_exception(kind, value, tb)
        def thread_hook(args):
            try:
                if args.exc_type is not SystemExit:
                    self.record_exception(args.exc_type, args.exc_value, args.exc_traceback)
            finally:
                previous_thread(args)
        self.hooks = (exception_hook, thread_hook)
        sys.excepthook, threading.excepthook = self.hooks

    def restore_hooks(self):
        if self.previous_hooks is None:
            return
        if sys.excepthook is self.hooks[0]:
            sys.excepthook = self.previous_hooks[0]
        if threading.excepthook is self.hooks[1]:
            threading.excepthook = self.previous_hooks[1]
        self.previous_hooks = None

    def close(self):
        if self.closed:
            return
        self.restore_hooks()
        try:
            with self.store._lock():
                if self.store._read(self.slot)['id'] != self.id:
                    raise DiagnosticUnavailable('Manager diagnostic identity changed.')
                if self.row['state'] == 'active':
                    self.store._path(self.slot).unlink()
        finally:
            self.closed = True
            self.lease.__exit__(None, None, None)
