"""Bounded diagnosis and manual-sharing projection; no execution or Qt imports."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from .redaction import ShareRedactor

MAX_LOG_BYTES = 262144
MAX_DIAGNOSTIC_BYTES = 16384


@dataclass(frozen=True)
class EvidenceRead:
    text: str
    status: str
    truncated: bool = False


@dataclass(frozen=True)
class Diagnosis:
    category: str
    title: str
    message: str
    step_id: str = ''
    test_id: str = ''
    evidence_status: str = ''
    hint: bool = False
    blockers: tuple = ()


def bounded(text, limit):
    raw = str(text).encode('utf-8', errors='replace')
    if len(raw) <= limit:
        return raw.decode('utf-8')
    suffix = '\n[truncated]'
    return raw[:max(0, limit - len(suffix))].decode('utf-8', errors='ignore') + suffix


def read_log(root, reference):
    """Read a complete-line prefix of a regular, non-linked retained log only."""
    root = Path(root)
    if (not isinstance(reference, str) or not reference or '\\' in reference
            or ':' in reference or Path(reference).is_absolute() or '..' in Path(reference).parts
            or root.is_symlink()):
        raise ValueError('Invalid retained log reference.')
    root = root.resolve()
    path = root / reference
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError('Linked retained logs are unavailable.')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Retained log must remain within its run.')
    try:
        # Avoid opening device/FIFO paths and reject final symlink replacement.
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('Retained log is not a regular file.')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Retained log is not a regular file.')
            raw = stream.read(MAX_LOG_BYTES + 1)
    except FileNotFoundError:
        return EvidenceRead('', 'missing')
    except OSError:
        return EvidenceRead('', 'unreadable')
    truncated = len(raw) > MAX_LOG_BYTES
    raw = raw[:MAX_LOG_BYTES]
    if truncated:
        raw = raw.rsplit(b'\n', 1)[0] + b'\n' if b'\n' in raw else b''
    return EvidenceRead(raw.decode('utf-8', errors='replace'),
                        'truncated' if truncated else 'available' if raw else 'empty', truncated)


def _case_id(case):
    return '.'.join(str(case.get(key, '')) for key in ('classname', 'name') if case.get(key))


def _message(text):
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    # Exception line explains the failure; traceback headings are not causes.
    exception = next((line for line in reversed(lines) if re.search(r'\b\w*(?:Error|Exception|Failure):', line)), '')
    return bounded(exception or next((line for line in lines if not line.startswith('Traceback')), ''), 2048)


def diagnose(plan, facts, *, outcome='', selected='', run_error='', log_text=''):
    facts = facts or {}
    if isinstance(facts, (list, tuple)):
        facts = {row['id']: row for row in facts if isinstance(row, dict) and 'id' in row}
    phases = {phase.id: phase for phase in plan.phases} if plan else {}
    if run_error and not selected:
        return Diagnosis('run', 'Run evidence incomplete', _message(run_error), evidence_status='incomplete')
    keys = list(phases) + [key for key in facts if key not in phases]
    problems = {'failed', 'error', 'timeout', 'crashed', 'interrupted', 'unknown'}
    key = selected if selected in phases or selected in facts else ''
    if not key:
        key = next((key for key in keys if facts.get(key, {}).get('status') == 'unknown'), '')
        key = key or next((key for key in keys if facts.get(key, {}).get('status') in problems
            or any(case.get('status') in {'failed', 'error', 'crashed', 'timeout'} for case in facts.get(key, {}).get('tests', ()))), '')
    row, phase = facts.get(key, {}), phases.get(key)
    state = row.get('status', '')
    label = getattr(phase, 'label', '') or key
    if state == 'unknown':
        return Diagnosis('unknown', 'Outcome unknown · ' + label,
            str(row.get('reason') or 'This action may have completed. Check its outcome before retrying.'), key)
    blockers = tuple(name for name in getattr(phase, 'dependencies', ()) if facts.get(name, {}).get('status')
                     in {'failed', 'error', 'timeout', 'crashed', 'interrupted', 'unknown', 'skipped', 'cancelled'})
    if state in {'blocked', 'skipped', 'queued'} and blockers:
        return Diagnosis('blocked', 'Blocked · ' + label,
            'This step did not run because a prerequisite did not pass: ' + ', '.join(blockers), key, blockers=blockers)
    if key and state not in problems:
        return Diagnosis('none', 'Step details', '', key)
    case = next((case for case in row.get('tests', ()) if case.get('status') in {'failed', 'error'}), None)
    if case:
        return Diagnosis('test', 'Test failed · ' + label, _message(case.get('message')) or 'No test error message was captured.',
            key, _case_id(case), 'reported')
    code = row.get('exit_code')
    observed = next((case for case in row.get('observed_test_failures', ()) if case.get('status') == 'crashed'), None)
    if state == 'crashed' or isinstance(code, int) and not isinstance(code, bool) and code < 0 or observed:
        return Diagnosis('process', 'Process crashed · ' + label,
            _message(row.get('error') or (observed or {}).get('message')) or f'The process ended abnormally (exit {code}).', key)
    if state == 'timeout':
        return Diagnosis('timeout', 'Step timed out · ' + label, _message(row.get('error') or row.get('reason')) or 'The step exceeded its time limit.', key)
    message = row.get('error') or row.get('reason')
    if message:
        return Diagnosis('error', 'Step failed · ' + label, _message(message), key)
    if log_text:
        line = next((line for line in str(log_text).splitlines() if re.search(
            r'(?i)\b(?:error|fatal|exception|missing|required .+not found|cannot|could not)\b', line)), '')
        if line:
            return Diagnosis('error', 'Step failed · ' + label, _message(line), key, evidence_status='captured output', hint=True)
    if state in problems:
        return Diagnosis('error', 'Step failed · ' + label, _message(row.get('summary')) or
            ('Process exited with code ' + str(code) + '.' if code is not None else 'No error message was captured.'), key)
    if run_error:
        return Diagnosis('run', 'Run evidence incomplete', _message(run_error), evidence_status='incomplete')
    if outcome in {'failed', 'error', 'unknown', 'interrupted', 'cancelled'}:
        return Diagnosis('run', 'Run ' + outcome, 'Inspect the retained outcomes; no more specific failure was captured.', evidence_status='incomplete')
    return Diagnosis('none', 'Step details' if key else 'Run summary', '', key)


def format_diagnostics(plan, report=None, *, facts=None, context=None, selected='', log_text='', include_excerpt=True, test_id='', secrets=()):
    """Project a small explicit allowlist. Never serialize source records or commands."""
    report, context = report or {}, context or {}
    facts = facts if facts is not None else report.get('phases', ())
    if not isinstance(facts, dict):
        facts = {row['id']: row for row in facts if isinstance(row, dict) and isinstance(row.get('id'), str)}
    if test_id and selected in facts:
        row = facts[selected]
        cases = row.get('tests', ())
        match = next((case for case in cases if _case_id(case) == test_id and case.get('status') in {'failed', 'error'}), None)
        if match:
            facts = dict(facts, **{selected: dict(row, tests=[match, *(case for case in cases if case is not match)])})
    redact = ShareRedactor(secrets)
    def clean(value, limit=160):
        return bounded(redact.text(value), limit)
    # Filter original streams before message extraction strips indentation or
    # selects one line out of a multiline key/source block.
    chosen = diagnose(plan, facts, outcome=report.get('status', ''), selected=selected).step_id
    safe_facts = {}
    for key, fact in facts.items():
        safe = {field: fact[field] for field in ('id', 'status', 'exit_code') if field in fact}
        if key == chosen:
            safe.update({field: redact.text(fact[field]) for field in ('error', 'reason', 'summary') if field in fact})
            case = next((case for case in fact.get('tests', ()) if case.get('status') in {'failed', 'error'}), None)
            safe['tests'] = [{field: redact.text(case.get(field, '')) for field in ('name', 'classname', 'status', 'message')}] if case else []
            observed = next((case for case in fact.get('observed_test_failures', ()) if case.get('status') == 'crashed'), None)
            safe['observed_test_failures'] = [{field: redact.text(observed.get(field, '')) for field in ('name', 'status', 'message')}] if observed else []
        safe_facts[key] = safe
    diagnosis = diagnose(plan, safe_facts, outcome=report.get('status', ''), selected=selected,
        run_error=redact.text(context.get('error', report.get('error', ''))), log_text=redact.text(log_text))
    lines = ['Build Deployment Manager diagnostics', 'Context: ' + clean(context.get('origin', 'Saved run' if report else 'Current run')),
             'Project: ' + clean(getattr(plan, 'project', None) or context.get('project', 'Not recorded')),
             'Operation: ' + clean(getattr(plan, 'operation', None) or context.get('operation', 'Not recorded')),
             'Preset: ' + clean(context.get('preset') or 'Not recorded', 100)]
    for label, value in (('Run', context.get('run_id')), ('Plan identity', report.get('plan_identity')),
                         ('Run outcome', report.get('status')), ('Step', diagnosis.step_id),
                         ('Category', diagnosis.category), ('Exception', context.get('exception'))):
        if value:
            lines.append(label + ': ' + clean(value))
    engine = report.get('engine', {})
    if isinstance(engine, dict):
        for name in ('manager', 'commonUtils'):
            item = engine.get(name, {})
            commit = item.get('commit') if isinstance(item, dict) else None
            if isinstance(commit, str) and re.fullmatch(r'[0-9a-f]{7,64}', commit):
                lines.append(name + ' revision: ' + commit)
        if type(engine.get('api')) is int:
            lines.append('Engine API: ' + str(engine['api']))
    for key, label in (('python_version', 'Viewer Python'), ('qt_version', 'Viewer Qt')):
        if context.get(key):
            lines.append(label + ': ' + clean(context[key]))
    if plan:
        lines.append('Execution: ' + clean(plan.backend))
        journey = plan.journey
        if isinstance(journey, dict):
            platforms = journey.get('platforms', {})
            targets = [name for name, steps in platforms.items() if not diagnosis.step_id or diagnosis.step_id in steps]
            if targets:
                lines.append('Platforms: ' + clean(', '.join(targets)))
    row = facts.get(diagnosis.step_id, {})
    if plan and diagnosis.step_id:
        phase = next((phase for phase in plan.phases if phase.id == diagnosis.step_id), None)
        if phase and phase.label:
            lines.append('Step label: ' + clean(phase.label))
    if type(row.get('exit_code')) is int:
        lines.append('Exit code: ' + str(row['exit_code']))
    lines += ['', 'Failure: ' + clean(diagnosis.message or context.get('error') or 'No failure detail recorded.', 2048)]
    if diagnosis.hint:
        lines.append('Source: captured-output hint; the recorded outcome is unchanged.')
    if diagnosis.blockers:
        lines.append('Unmet prerequisites: ' + clean(', '.join(diagnosis.blockers), 1024))
    cases = [case for fact in facts.values() for case in fact.get('tests', ()) if case.get('status') in {'failed', 'error'}]
    if cases:
        lines.append('\nFailed tests: ' + str(len(cases)))
        lines += ['- ' + clean(_case_id(case), 250) + ' (' + clean(case.get('status'), 20) + ') · suite ' +
                  clean(case.get('suite') or 'Not recorded', 100) for case in cases[:20]]
        if len(cases) > 20:
            lines.append('[additional test identifiers omitted]')
    states = {}
    for fact in facts.values():
        state = fact.get('status', 'unknown')
        states[state] = states.get(state, 0) + 1
    if states:
        lines.append('Step outcomes: ' + clean(', '.join(str(count) + ' ' + str(state) for state, count in states.items()), 600))
    if plan:
        deliveries = [phase for phase in plan.phases if (phase.effect if phase.effect != 'inherit' else plan.effect)
                      in {'deploy', 'upload', 'publish', 'dispatch'}]
        if deliveries:
            counts = dict(completed=0, blocked=0, unknown=0, failed=0, pending=0)
            for phase in deliveries:
                state = facts.get(phase.id, {}).get('status', 'queued')
                category = ('completed' if state == 'passed' else 'unknown' if state == 'unknown' else
                            'blocked' if state in {'skipped', 'blocked'} else 'failed' if state in
                            {'failed', 'error', 'timeout', 'crashed'} else 'pending')
                counts[category] += 1
            lines.append('Delivery actions: ' + ', '.join(str(value) + ' ' + name for name, value in counts.items()))
    if any(fact.get('status') == 'unknown' for fact in facts.values()) or report.get('status') == 'unknown':
        lines.append('Unknown actions may have completed. Reconcile their outcomes before retrying.')
    excerpt = ''
    if include_excerpt:
        case = next((case for case in row.get('tests', ()) if case.get('status') in {'failed', 'error'}), None)
        source = case.get('message', '') if case else log_text or context.get('traceback', '')
        safe = redact.text(source)
        if safe:
            excerpt_lines = safe.splitlines()
            match = next((i for i, line in enumerate(excerpt_lines) if re.search(r'(?i)\b(?:error|fatal|exception|missing)\b', line)), 0)
            start = max(0, match - 3)
            chosen_lines = []
            used = 0
            for line in excerpt_lines[start:start + 79]:
                cost = len(line.encode('utf-8')) + 1
                if used + cost > 8150:
                    break
                chosen_lines.append(line)
                used += cost
            excerpt = '\n'.join(chosen_lines)
            if start or len(excerpt_lines) > start + len(chosen_lines):
                excerpt += '\n[excerpt; other lines omitted]'
    lines += ['', 'Evidence: ' + clean(context.get('evidence_status') or diagnosis.evidence_status or
                                     ('available excerpt' if excerpt else 'No excerpt available.'))]
    lines += ['Excerpt:\n' + excerpt] if excerpt else ['Excerpt omitted.' if not include_excerpt else 'No log or traceback excerpt available.']
    lines += ['', 'Local preview for manual sharing. Recorded outcomes are unchanged.']
    complete, used = [], 0
    for line in '\n'.join(lines).splitlines():
        cost = len(line.encode('utf-8')) + 1
        if used + cost > MAX_DIAGNOSTIC_BYTES - 32:
            complete.append('[additional details omitted]')
            break
        complete.append(line)
        used += cost
    return '\n'.join(complete)
