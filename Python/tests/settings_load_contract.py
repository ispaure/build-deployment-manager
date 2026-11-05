"""Test-only request/retirement timing, distinct from Qt rendering readiness."""
import inspect
from threading import Event, Lock
import time


class TimedEvent:
    """Record actual completion before publication, not the observer's wakeup."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.event, self.lock = clock, Event(), Lock()
        self._completed = None

    def set(self):
        with self.lock:
            if not self.event.is_set():
                self._completed = self.clock()
                self.event.set()

    def is_set(self):
        return self.event.is_set()

    def completion_time(self):
        with self.lock:
            return self._completed if self.event.is_set() else None


class TaskCompletions:
    """A completion belongs to one exact QRunnable, never another pool task."""
    def __init__(self):
        self.lock, self.rows = Lock(), {}

    def event(self, task):
        with self.lock:
            row = self.rows.get(id(task))
            if row is None:
                row = self.rows[id(task)] = (task, TimedEvent())
            assert row[0] is task  # Retain identity until this fixture retires.
            return row[1]

    def call(self, callback, task):
        return completed_call(callback, self.event(task), task)


class BridgeRetirement:
    """Only the exact fixture root AND declared child command can retire it."""
    def __init__(self, root, argv):
        from pathlib import Path
        self.root, self.argv = Path(root).absolute(), tuple(map(str, argv))
        self.entered, self.retired = TimedEvent(), TimedEvent()

    def call(self, callback, *args, **kwargs):
        from pathlib import Path
        owned = (args and tuple(map(str, args[0])) == self.argv
                 and kwargs.get('cwd') is not None
                 and Path(kwargs['cwd']).absolute() == self.root)
        if not owned:
            return callback(*args, **kwargs)
        self.entered.set()
        value = callback(*args, **kwargs)
        self.retired.set()
        return value


def budgets(loader, *, stop_grace, drain_timeout):
    request = inspect.signature(loader).parameters['timeout'].default
    if not isinstance(request, (int, float)) or request <= 0:
        raise ValueError('Settings loader requires a declared positive request timeout.')
    # POSIX: TERM+5 session budget, followed by either root reap/drain or
    # root-only fallback TERM+5. Windows: TERM, root reap, job wait, pipe drain.
    posix = stop_grace + 5 + max(5 + drain_timeout, stop_grace + 5)
    windows = stop_grace + 5 + 5 + drain_timeout
    retirement = max(posix, windows)
    return dict(request=request, retirement=retirement, worker=1 + request + retirement)


def completed_call(callback, finished, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    finally:
        finished.set()


def wait_for_event(case, event, budget, pump, *, stage, clock=time.monotonic, pause=time.sleep):
    deadline = clock() + budget
    while True:
        completed = event.completion_time()
        if completed is not None:
            case.assertLessEqual(completed, deadline, stage + ' completed after its declared deadline')
            return
        if clock() >= deadline:
            # A timely completion can race an observer delayed by its Qt turn.
            completed = event.completion_time()
            case.assertIsNotNone(completed, stage + ' did not finish within its declared budget')
            case.assertLessEqual(completed, deadline, stage + ' completed after its declared deadline')
            return
        pump()
        pause(.005)


def cleanup_fixture(temporary, *, attempted, task_finished, bridge_entered, bridge_retired):
    if not attempted or (task_finished and (not bridge_entered or bridge_retired)):
        temporary.cleanup()
        return True
    return False  # Preserve this synthetic tree; no inference from UI closure.


def finish_cleanup(primary, callbacks):
    """Try all owned cleanup; preserve a latched failure, never hide a sole one."""
    errors = []
    for callback in callbacks:
        try:
            callback()
        except BaseException as error:
            errors.append(error)
    if errors:
        if primary is None:
            raise errors[0]
        for error in errors:
            try:
                primary.add_note('Settings fixture cleanup failure: ' + type(error).__name__)
            except Exception:
                pass  # Annotation cannot replace the already-latched failure.
