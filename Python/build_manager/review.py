"""Retained, cancellable verification with no widget or adapter access."""
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable


@dataclass(frozen=True)
class Continuation:
    path: Path
    plan: object
    report: dict
    steps: tuple
    approvals: tuple
    engine_change: object = None


class VerifyContinuation(QRunnable):
    def __init__(self, path, descriptor, checkout, revision, results):
        super().__init__()
        self.path = Path(path)
        self.descriptor, self.checkout = dict(descriptor), str(checkout)
        self.revision, self.results = revision, results
        self.cancelled, self.done = Event(), Event()

    def run(self):
        from .history import load_run
        from .workflows import recover, approve
        from commonUtils.runtime.operations import check_cancelled
        try:
            check_cancelled(self.cancelled.is_set)
            plan, report = load_run(self.path)
            if self.descriptor and plan.project != self.descriptor['name']:
                raise ValueError('This run belongs to a different selected project.')
            if self.descriptor and plan.adapter and (
                    plan.adapter.get('project_id') != self.descriptor['project_id']
                    or plan.adapter.get('checkout') != self.checkout):
                raise ValueError('This run belongs to a different registered checkout.')
            recover(plan, report, cancelled=self.cancelled.is_set, preserve_unknown=True)
            steps = tuple(row['id'] for row in report['phases'] if row['status'] == 'awaiting_review')
            approvals = tuple(approve(plan, step, report, cancelled=self.cancelled.is_set) for step in steps)
            check_cancelled(self.cancelled.is_set)
            from .identity import runtime_identity, engine_review_identity
            current = runtime_identity()
            change = None
            if report.get('engine') is not None and report['engine'] != current:
                change = dict(previous=report['engine'], current=current,
                              identity=engine_review_identity(report['engine'], current))
            value = Continuation(self.path, plan, report, steps, approvals, change)
            self.results.put((self.revision, value, None))
        except Exception as error:
            self.results.put((self.revision, None, str(error)))
        finally:
            self.done.set()
