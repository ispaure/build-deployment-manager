"""One explicitly opted-in test recovery, supervised by the normal executor.

Trusted project subprocesses supply platform/worker evidence; no project or Qt
modules are imported. Commands are part of the reviewed plan identity.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from commonUtils.runtime.operations import OperationCancelled, check_cancelled
from commonUtils.runtime.streams import file_sha256
from .profiles import save_json
from .redaction import Redactor
from .run_recording import timestamp


def validate_policy(phase):
    policy = phase.infrastructure_recovery
    if not isinstance(policy, dict):
        raise ValueError('Infrastructure recovery must be a structured policy.')
    if not policy:
        return
    fields = {'environment', 'target', 'resource', 'safe_to_repeat', 'probe', 'recover', 'inputs', 'timeout'}
    if set(policy) != fields:
        raise ValueError('Infrastructure recovery needs an explicit target, commands, inputs and bounded timeout.')
    if (phase.effect != 'test' or phase.kind != 'test' or phase.always or phase.provider
            or policy['safe_to_repeat'] is not True):
        raise ValueError('Only explicitly repeatable test units may recover infrastructure.')
    if policy['environment'] not in ('android', 'ios', 'vm'):
        raise ValueError('Recovery supports Android, iOS Simulator and owned test VMs.')
    if any(not isinstance(policy[key], str) or not policy[key] or len(policy[key]) > 1000
           or '\x00' in policy[key] for key in ('target', 'resource')):
        raise ValueError('Recovery needs a stable target and exclusive resource identity.')
    if phase.resources.get(policy['resource']) != 1:
        raise ValueError('The recovery target must be locked for the entire test phase.')
    for key in ('probe', 'recover'):
        if (not isinstance(policy[key], (list, tuple)) or not policy[key]
                or any(not isinstance(arg, str) or not arg or '\x00' in arg for arg in policy[key])):
            raise ValueError('Recovery commands must be structured argument lists.')
    if type(policy['timeout']) not in (int, float) or not 1 <= policy['timeout'] <= 600:
        raise ValueError('Recovery checks and repair share a deadline of 1–600 seconds.')
    inputs = policy['inputs']
    if (not isinstance(inputs, dict) or not inputs or len(inputs) > 1000
            or any(not isinstance(path, str) or not Path(path).is_absolute() or '\x00' in path
                   or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                   for path, digest in inputs.items())):
        raise ValueError('Recovery requires absolute prepared-input paths and SHA-256 digests.')
    for output in phase.artifacts:
        if not Path(output).is_absolute():
            raise ValueError('Recovery test outputs must use absolute paths.')
        for source in inputs:
            if (Path(output).resolve() == Path(source).resolve()
                    or Path(output).exists() and Path(source).exists() and Path(output).samefile(source)):
                raise ValueError('Prepared recovery inputs cannot also be mutable test outputs.')


def _read_record(path):
    """Damaged retained state stops recovery, not the independent workflow."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('Record is too large.')
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError('Expected an object.')
        return record
    except (ValueError, RecursionError) as error:
        raise ValueError('Invalid infrastructure recovery record: ' + str(path)) from error


def validate_result_recovery(row):
    """Validate persisted recovery facts before UI or resume code consumes them."""
    observations = row.get('observed_test_failures', [])
    if (not isinstance(observations, list) or any(not isinstance(item, dict)
            or item.get('status') not in ('failed', 'error', 'crashed', 'timeout')
            or any(key in item and not isinstance(item[key], str) for key in ('name', 'message'))
            for item in observations)):
        raise ValueError('Invalid infrastructure recovery failure observations.')
    if 'recovery' not in row:
        return
    info = row['recovery']
    if (not isinstance(info, dict) or info.get('environment') not in ('android', 'ios', 'vm')
            or not isinstance(info.get('target'), str) or not info['target']
            or info.get('status') not in ('checking', 'not-needed', 'not-safe', 'not-confirmed',
                'recovering', 'recovered', 'exhausted', 'failed', 'cancelled', 'interrupted')
            or info.get('status') == 'recovered' and row.get('status') != 'passed'):
        raise ValueError('Invalid infrastructure recovery evidence.')
    for key in ('attempts', 'checks'):
        if not isinstance(info.get(key), list):
            raise ValueError('Invalid infrastructure recovery evidence.')
        for attempt in info[key]:
            if (not isinstance(attempt, dict)
                    or attempt.get('status') not in ('passed', 'failed', 'timeout', 'cancelled')
                    or any(field in attempt and not isinstance(attempt[field], str)
                           for field in ('log', 'operation'))):
                raise ValueError('Invalid infrastructure recovery attempt evidence.')


def _read_journal(path, policy, phase_id):
    saved = _read_record(path)
    row = saved.get('result')
    if (saved.get('state') not in ('admitted', 'finished') or not isinstance(row, dict)
            or row.get('id') != phase_id or type(row.get('required')) is not bool
            or row.get('status') not in ('passed', 'failed', 'timeout', 'cancelled')
            or not isinstance(row.get('recovery'), dict)):
        raise ValueError('Invalid infrastructure recovery record: ' + str(path))
    info = row['recovery']
    try:
        validate_result_recovery(row)
    except ValueError as error:
        raise ValueError('Invalid infrastructure recovery record: ' + str(path)) from error
    if (info.get('target') != policy['target'] or info.get('environment') != policy['environment']
            or not isinstance(row.get('artifacts', []), list)
            or any(not isinstance(artifact, dict)
                   or any(not isinstance(artifact.get(key), str) for key in ('path', 'sha256'))
                   or 'original_path' in artifact and not isinstance(artifact['original_path'], str)
                   for artifact in row.get('artifacts', []))
            or row['status'] == 'passed' and info.get('status') != 'recovered'):
        raise ValueError('Invalid infrastructure recovery record: ' + str(path))
    return saved


def execute(phase, output, run, *, cancelled, event):
    """Keep target resources held across checks, recovery and one fresh test run.

    The journal is written before repair admission. A supervisor restart never
    admits a second repair or silently replays an uncertain recovery attempt.
    """
    policy = phase.infrastructure_recovery
    if not policy:
        return run(phase, output)
    def verify_inputs():
        for path, digest in policy['inputs'].items():
            check_cancelled(cancelled)
            if file_sha256(Path(path), cancelled=cancelled) != digest:
                raise ValueError('Prepared recovery input changed: ' + path)

    root = Path(output).resolve()
    journal = root / 'infrastructure-recovery' / phase.id / 'recovery.json'
    target_key = hashlib.sha256(json.dumps([policy['environment'], policy['target']]).encode()).hexdigest()
    budget = root / 'infrastructure-recovery' / 'targets' / (target_key + '.json')
    if journal.exists():
        if not budget.exists():
            raise ValueError('Infrastructure recovery record has lost its target admission; inspect a new run.')
        saved = _read_journal(journal, policy, phase.id)
        row = dict(saved['result'], required=phase.required, kind=phase.kind)
        if saved['state'] != 'finished':
            row = dict(row, status='failed', failure_kind='infrastructure',
                       recovery=dict(row.get('recovery', {}), status='interrupted'),
                       reason='Infrastructure recovery was interrupted; inspect retained evidence and start a new run.')
        elif row['status'] == 'passed':
            from .workflows import verify_artifacts
            verify_inputs()
            verify_artifacts(row, cancelled=cancelled)
        return row
    if budget.exists():
        admission = _read_record(budget)
        owner = admission.get('phase')
        if (not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', owner)
                or admission.get('status') not in ('admitted', 'recovered', 'failed')
                or admission.get('target') != policy['target'] or admission.get('environment') != policy['environment']):
            raise ValueError('Invalid infrastructure recovery record: ' + str(budget))
        owner_journal = journal.parent.parent / owner / 'recovery.json'
        if admission['status'] == 'admitted' and owner_journal.exists():
            completed = _read_journal(owner_journal, policy, owner)
            if completed['state'] == 'finished':
                if completed['result']['status'] == 'passed':
                    from .workflows import verify_artifacts
                    verify_artifacts(completed['result'], cancelled=cancelled)
                    admission['status'] = 'recovered'
                else:
                    admission['status'] = 'failed'
                save_json(budget, admission)
        if admission['status'] != 'recovered':
            return dict(id=phase.id, required=phase.required, kind=phase.kind, status='skipped',
                        failure_kind='infrastructure', seconds=0,
                        reason='This target has failed or interrupted infrastructure recovery; inspect a new run.')

    attempt_root = journal.parent / uuid4().hex
    started = time.monotonic()
    attempts, checks = [], []
    info = dict(environment=policy['environment'], target=policy['target'],
                status='checking', attempts=attempts, checks=checks)

    def invoke(command, label):
        check_cancelled(cancelled)
        def signature(value):
            try:
                stat = Path(value).stat()
                return stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
            except FileNotFoundError:
                return None
        previous = {value: signature(value) for value in command.artifacts}
        destination = attempt_root / label
        destination.mkdir(parents=True, exist_ok=False)
        row = run(command, destination)
        if row['status'] == 'passed' and row.get('observed_test_failures'):
            row.update(status='failed', error='Runner reported app/test failures despite a successful exit.')
        if row['status'] == 'passed' and any(signature(value) == old for value, old in previous.items()):
            row.update(status='failed', error='Test runner did not produce fresh declared output.')
        if row.get('log'):
            row['log'] = str((destination / row['log']).relative_to(root))
        return row

    def finish(row):
        row = dict(row, recovery=info, seconds=time.monotonic() - started, finished_at=timestamp())
        if attempts:
            row['started_at'] = attempts[0]['started_at']
        if journal.exists():
            save_json(journal, dict(state='finished', result=row))
            save_json(budget, dict(phase=phase.id, target=policy['target'],
                                  environment=policy['environment'],
                                  status='recovered' if row['status'] == 'passed' else 'failed'))
        return row

    def hook(key, label, action):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('Infrastructure recovery deadline expired.')
        command = replace(phase, argv=tuple(policy[key]), timeout=remaining,
            environment=dict(phase.environment, BUILD_MANAGER_RECOVERY_TARGET=policy['target'],
                             BUILD_MANAGER_RECOVERY_ACTION=action),
            artifacts=(), artifact_types={}, test_files=(), infrastructure_recovery={},
            reuse_key='', reuse_probe=())
        row = invoke(command, label)
        checks.append(dict(row, operation=label))
        if row['status'] != 'passed' or row.get('cleanup_error'):
            raise RuntimeError('Infrastructure ' + label + ' did not complete successfully.')
        return row

    def probe(label):
        row = hook('probe', label, 'probe')
        path = root / row['log']
        if path.stat().st_size > 65536:
            raise ValueError('Infrastructure probe exceeded its evidence limit.')
        proof = json.loads(path.read_text())
        if (not isinstance(proof, dict) or proof.get('schema') != 1
                or proof.get('target') != policy['target']
                or proof.get('state') not in ('ready', 'stopped', 'disconnected', 'unknown')
                or any(proof.get(key) is not True for key in ('owned', 'exclusive', 'worker_stopped'))
                or proof.get('held') is not False):
            raise ValueError('Probe did not establish an owned, unheld target with no surviving test worker.')
        if proof['state'] in ('stopped', 'disconnected') and proof.get('failure_kind') != 'infrastructure':
            raise ValueError('Probe did not classify the interrupted test as an infrastructure failure.')
        # Keep the bounded protocol fields, not arbitrary unredacted diagnostics.
        checks[-1]['proof'] = {key: proof[key] for key in
            ('schema', 'target', 'state', 'owned', 'exclusive', 'worker_stopped', 'held')}
        checks[-1]['proof']['failure_kind'] = proof.get('failure_kind', '')
        return proof['state']

    row = dict(id=phase.id, required=phase.required, kind=phase.kind, status='failed')
    try:
        verify_inputs()
        row = invoke(phase, 'first')
        attempts.append(dict(row))
        if row['status'] not in ('failed', 'timeout') or cancelled():
            info['status'] = 'not-needed'
            return finish(row)
        # A known test failure cannot be erased by a coincident environment failure.
        if row.get('cleanup_error') or row.get('observed_test_failures') or any(
                case.get('status') in ('failed', 'error', 'crashed', 'timeout')
                for key in ('tests', 'live_tests', 'test_files') for case in row.get(key, ())):
            info['status'] = 'not-safe'
            row['reason'] = ('Automatic recovery withheld because process cleanup was incomplete.'
                             if row.get('cleanup_error') else
                             'Automatic recovery withheld because an app/test failure was reported.')
            return finish(row)
        deadline = time.monotonic() + policy['timeout']
        state = probe('diagnose')
        if state not in ('stopped', 'disconnected'):
            info['status'] = 'not-confirmed'
            return finish(row)
        row = dict(row, failure_kind='infrastructure')
        if budget.exists():
            info['status'] = 'exhausted'
            row['reason'] = 'This target already used its infrastructure recovery attempt in this run.'
            save_json(budget, dict(phase=phase.id, target=policy['target'],
                                  environment=policy['environment'], status='failed'))
            return finish(row)
        verify_inputs()
        check_cancelled(cancelled)
        info['status'] = 'recovering'
        # Persist admission before invoking any lifecycle mutation.
        save_json(budget, dict(phase=phase.id, target=policy['target'],
                              environment=policy['environment'], status='admitted'))
        save_json(journal, dict(state='admitted', result=dict(row, recovery=info)))
        event(dict(type='phase', id=phase.id, status='running',
                   reason='Recovering test infrastructure (one attempt).'))
        hook('recover', 'repair', 'restart' if state == 'stopped' else 'reconnect')
        if probe('readiness') != 'ready':
            raise RuntimeError('Recovered environment did not prove readiness.')
        verify_inputs()
        check_cancelled(cancelled)
        if time.monotonic() >= deadline:
            raise RuntimeError('Infrastructure recovery deadline expired before replay.')
        row = invoke(phase, 'second')
        attempts.append(dict(row))
        if row['status'] == 'passed':
            info['status'] = 'recovered'
            row['reason'] = 'Passed after infrastructure recovery.'
        else:
            info['status'] = 'exhausted'
            row['reason'] = 'Test did not pass after the single infrastructure recovery attempt.'
        return finish(row)
    except (OSError, ValueError, RuntimeError, OperationCancelled) as error:
        info['status'] = 'cancelled' if cancelled() else 'failed'
        row = dict(row, status='cancelled' if cancelled() else 'failed',
                   reason=Redactor()(str(error)))
        return finish(row)
