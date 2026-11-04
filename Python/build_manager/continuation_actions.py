"""Headless continuation choices; guidance never authorizes or executes work."""
from dataclasses import dataclass
from pathlib import Path

from .workflows import EXTERNAL


@dataclass(frozen=True)
class ContinuationSelection:
    steps: tuple[str, ...] | None
    retry_failed: bool = True


def continuation_label(report):
    rows = report['phases']
    pending = [row for row in rows if row['status'] == 'awaiting_review']
    failed = any(row['status'] in {'failed', 'skipped', 'cancelled', 'timeout', 'interrupted'} for row in rows)
    if report['status'] == 'unknown':
        return 'Continue independent steps…'
    if pending and failed:
        return 'Continue ready delivery…'
    if any(row.get('effect') == 'dispatch' for row in pending):
        return 'Review and start GitHub checks…'
    if pending:
        return 'Review and continue delivery…'
    return 'Retry unfinished steps…'


def continuation_guidance(report, output):
    rows = report['phases']
    completed = [row['id'] for row in rows
                 if row['status'] == 'passed' and row.get('effect') in EXTERNAL]
    pending = [row['id'] for row in rows if row['status'] == 'awaiting_review']
    failed = [row['id'] for row in rows
              if row['status'] in {'failed', 'skipped', 'cancelled', 'timeout', 'interrupted'}]
    unknown = [row['id'] for row in rows if row['status'] == 'unknown']
    actions = []
    if not report.get('retirement') and report['status'] not in {'queued', 'running'}:
        output = str(Path(output).resolve())
        if pending:
            actions.append(dict(id='review', label='Inspect prepared files and pending delivery',
                                argv=['build-manager', 'review', output]))
            argv = ['build-manager', 'resume', output, '--no-retry-failed', '--confirm']
            if report.get('plan_identity'):
                argv += ['--expect-identity', report['plan_identity']]
            for step in pending:
                argv += ['--approve-step', step]
            actions.append(dict(id='continue-ready',
                label='Authorize named pending actions; preserve failed checks and blocked steps', argv=argv))
        if failed:
            actions.append(dict(id='retry-failed', label='Retry failed checks and their blocked steps',
                                argv=['build-manager', 'resume', output]))
    return dict(completed_actions=completed, pending_actions=pending, failed_steps=failed,
                unknown_steps=unknown, next_actions=actions,
                warning='Unknown external outcomes require reconciliation and are never repeated automatically.'
                        if unknown else '')
