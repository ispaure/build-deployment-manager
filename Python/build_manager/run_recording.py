"""Private run report persistence and attempt timing, without scheduling policy."""
from datetime import datetime, timezone
import os
import time
from typing import Any, TypedDict

from .history import valid_seconds
from .profiles import save_json
from .redaction import Redactor


class RunReport(TypedDict, total=False):
    status: str
    phases: list[dict[str, Any]]
    seconds: float
    attempt_seconds: float
    attempts: list[dict[str, Any]]
    started_at: str
    finished_at: str
    error: str


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def sanitized_report(value, redact):
    if isinstance(value, str):
        # Report values are independent strings, not consecutive PEM lines.
        redact.private_key = False
        return redact(value)
    if isinstance(value, dict):
        return {key: sanitized_report(item, redact) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitized_report(item, redact) for item in value]
    return value


class RunRecorder:
    def __init__(self, output, report: RunReport, secret_environment, *, resume=False,
                 clock=time.monotonic):
        self.output, self.report = output, report
        self.secret_environment = secret_environment
        self.clock = clock
        self.started = clock()
        self.previous_seconds = report.get('seconds', 0) if resume else 0
        if not valid_seconds(self.previous_seconds) or not isinstance(report.get('attempts', []), list):
            raise ValueError('Retained run timing is invalid; preserve and inspect a new run.')
        self.attempt_started_at = timestamp()

    def save(self):
        redact = Redactor(os.environ.get(name) for name in self.secret_environment)
        save_json(self.output / 'result.json', sanitized_report(self.report, redact))

    def finish_timing(self, *, retry_failed=True):
        elapsed = self.clock() - self.started
        self.report.update(finished_at=timestamp(), attempt_seconds=elapsed,
                           seconds=self.previous_seconds + elapsed)
        attempt = dict(started_at=self.attempt_started_at, finished_at=self.report['finished_at'],
                       seconds=elapsed, status=self.report['status'])
        if not retry_failed:
            attempt['retry_failed'] = False
        if self.report.get('error'):
            attempt['error'] = self.report['error']
        self.report.setdefault('attempts', []).append(attempt)
