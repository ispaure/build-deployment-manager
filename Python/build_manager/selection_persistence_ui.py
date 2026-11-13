"""Coalesce remembered GUI choices without blocking event dispatch on storage."""
from copy import deepcopy
from queue import Empty, Queue

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal


class SaveSelections(QRunnable):
    def __init__(self, registry, batch, results):
        super().__init__()
        self.registry, self.batch, self.results = registry, batch, results

    def run(self):
        errors = {}
        for key, choices in self.batch.items():
            try:
                self.registry.save_selections(key, choices)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                errors[key] = str(error)
        self.results.put((self.batch, errors))


class SelectionPersistence(QObject):
    """One writer per window; latest choices also serve newly opened run tabs."""
    settled = Signal()
    failed = Signal(str)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.latest, self.pending = {}, {}
        self.unsaved = {}
        self.results = Queue()
        self.active = False
        self.callbacks = []
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.poll)

    def submit(self, key, choices):
        choices = deepcopy(choices)
        if self.latest.get(key) == choices and key not in self.unsaved:
            return
        self.latest[key] = choices
        self.pending[key] = choices
        self.unsaved.pop(key, None)
        self.timer.start()

    def choices(self, key, fallback):
        return deepcopy(self.latest.get(key, fallback))

    def flush(self, *, retry=False):
        if retry:
            for key, choices in self.unsaved.items():
                self.pending.setdefault(key, choices)
            self.unsaved.clear()
        if self.pending and not self.active:
            batch, self.pending = self.pending, {}
            self.active = True
            QThreadPool.globalInstance().start(SaveSelections(self.registry, batch, self.results))
            self.timer.start()
        return not self.active and not self.pending and not self.unsaved

    def discard_unsaved(self):
        """Called only after explicit close-without-saving approval."""
        self.unsaved.clear()

    def after_flush(self, callback):
        if self.flush(retry=True):
            callback()
        else:
            self.callbacks.append(callback)

    def poll(self):
        try:
            batch, errors = self.results.get_nowait()
        except Empty:
            batch = None
        if batch is not None:
            self.active = False
            for key, choices in batch.items():
                if key in errors:
                    self.unsaved[key] = self.pending.get(key, choices)
                else:
                    self.unsaved.pop(key, None)
            if errors:
                queued = bool(self.callbacks)
                self.callbacks.clear()
                message = 'Could not remember run choices: ' + '; '.join(errors.values())
                if queued:
                    message += '. The queued change was not saved; try it again.'
                self.failed.emit(message + '. Edit choices or close again to retry.')
        if self.flush():
            self.timer.stop()
            callbacks, self.callbacks = self.callbacks, []
            for callback in callbacks:
                callback()
            self.settled.emit()
        elif not self.active and not self.pending:
            # Retain failed values for an explicit retry; never spin on a lock
            # or close the window as though an unsuccessful write had settled.
            self.timer.stop()
