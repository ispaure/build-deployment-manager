"""Owned background preparation; a retired request never touches its widgets."""
from dataclasses import dataclass
from queue import Queue
from threading import Event
import traceback

from PySide6.QtCore import QRunnable


class PreparationFailure(str):
    def __new__(cls, message, details):
        failure = super().__new__(cls, message)
        failure.details = details
        return failure


@dataclass(frozen=True)
class PreparedResult:
    job: object
    plan: object = None
    review: object = None
    error: object = None


class PreparePlan(QRunnable):
    """One admitted request, including cooperative cancellation and teardown."""
    def __init__(self, prepare, results, *, transform=None):
        super().__init__()
        self.prepare, self.results, self.transform = prepare, results, transform
        self.cancelled, self.done = Event(), Event()
        self.progress = Queue()
        self.revision = 0
        self.reason = ''

    def report(self, message):
        self.progress.put(message)

    def run(self):
        plan = review = error = None
        try:
            if not self.cancelled.is_set():
                plan = self.prepare()
                from .models import Plan
                if not isinstance(plan, Plan):
                    raise ValueError('The project adapter did not return an operation plan.')
                if not self.cancelled.is_set() and self.transform is not None:
                    self.report('Preparing the review display')
                    plan, review = self.transform(plan)
        except Exception as caught:
            error = PreparationFailure(str(caught), traceback.format_exc())
        finally:
            # Completion means the callable and any bridge-owned cleanup returned.
            self.done.set()
            self.results.put(PreparedResult(self, plan, review, error))


class ReadRetainedRun(QRunnable):
    def __init__(self, path, results, *, fields=(), capability=None):
        super().__init__()
        self.path, self.results = path, results
        self.cancelled, self.done = Event(), Event()
        self.fields, self.capability, self.review = fields, capability, None

    def run(self):
        plan = report = error = None
        try:
            from .history import load_run
            if not self.cancelled.is_set():
                plan, report = load_run(self.path)
                if not self.cancelled.is_set():
                    from .review_presentation import prepare_review_data
                    self.review = prepare_review_data(plan, fields=self.fields, capability=self.capability)
        except Exception as caught:
            error = str(caught)
        finally:
            self.done.set()
            self.results.put((self, plan, report, error))
