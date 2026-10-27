"""Publicly verifiable exports of authenticated local test receipts.

The project supplies exact coverage bindings and the receiver's trust file.
This module never decides that different platforms or toolchains are equivalent.
SSH signing keeps the private key outside repositories and CI environments.
"""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from .evidence import canonical

NAMESPACE = 'build-manager-test-evidence-v1'
MAX_BYTES = 4 * 1024 * 1024


def _ssh(arguments, *, data=None):
    return subprocess.run(['ssh-keygen', *arguments], input=data, capture_output=True,
                          check=True, timeout=15).stdout


def export_receipts(cache, phases, bindings, private_key, *, now=None):
    """Sign only authentic passed cache entries, never caller-provided results.

    Bindings are public project policy (source/dependencies/coverage/toolchain).
    Original logs, machine paths, environment values and credentials are excluded.
    Missing or altered evidence aborts export rather than signing a partial pass.
    """
    private_key = Path(private_key)
    if (private_key.is_symlink() or not private_key.is_file()
            or os.name != 'nt' and private_key.stat().st_mode & 0o077):
        raise ValueError('Evidence signing requires a private regular key file.')
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError('Explicit public coverage bindings are required.')
    entries = []
    key = cache.key()
    for phase in phases:
        if not phase.reuse_key or phase.effect != 'test' or phase.kind != 'test' or phase.always:
            raise ValueError('Only input-bound test phases can be exported.')
        receipt = cache.read(phase, key)
        if receipt is None:
            raise ValueError('Missing or invalid authenticated receipt: ' + phase.id)
        row = receipt['row']
        entries.append(dict(step=phase.id, inputs=phase.reuse_key,
            finished_at=row.get('finished_at'),
            artifacts=[dict(sha256=item['sha256'], kind=item.get('kind', 'file'))
                       for item in row.get('artifacts', [])]))
    if not entries or len({item['step'] for item in entries}) != len(entries):
        raise ValueError('Evidence needs unique test steps.')
    payload = dict(schema=1, issued_at=(now or datetime.now(timezone.utc)).isoformat(),
                   bindings=json.loads(canonical(bindings)), tests=entries)
    data = canonical(payload)
    if len(data) > MAX_BYTES:
        raise ValueError('Evidence exceeds the inspection budget.')
    # Signing stdin emits an armored SSH signature on stdout. No private key
    # bytes are copied into the envelope or staging directory.
    signature = _ssh(['-Y', 'sign', '-f', str(private_key), '-n', NAMESPACE], data=data)
    return dict(payload=payload, signature=base64.b64encode(signature).decode('ascii'))


def verify_export(envelope, allowed_signers, signer, expected_bindings, expected_tests,
                  *, now=None, max_age=timedelta(hours=24), allow_additional_tests=False):
    """Return verified proof or raise; callers run fresh checks on rejection.

    expected_tests maps each required step to its independently derived input key.
    A receiver checking one suite in a larger export may explicitly permit extra
    signed tests; its required subset must still match exactly and be nonempty.
    A signature alone never establishes equivalent coverage. Both the envelope
    and each original test completion must be recent (re-export cannot renew it).
    """
    if not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,200}', signer):
        raise ValueError('Invalid evidence signer identity.')
    if (not isinstance(expected_bindings, dict) or not expected_bindings
            or not isinstance(expected_tests, dict) or not expected_tests):
        raise ValueError('Independent source and coverage expectations are required.')
    data = canonical(envelope)
    if len(data) > MAX_BYTES:
        raise ValueError('Evidence exceeds the inspection budget.')
    payload = envelope['payload']
    if payload['schema'] != 1 or payload['bindings'] != expected_bindings:
        raise ValueError('Evidence source, dependencies or coverage changed.')
    tests = payload['tests']
    actual = {item['step']: item['inputs'] for item in tests}
    matches = (all(actual.get(step) == key for step, key in expected_tests.items())
               if allow_additional_tests else actual == expected_tests)
    if len(actual) != len(tests) or not matches:
        raise ValueError('Evidence test inputs do not match required coverage.')
    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in actual.values()):
        raise ValueError('Evidence input identities must be SHA-256 hashes.')
    now = now or datetime.now(timezone.utc)
    if not timedelta(0) < max_age <= timedelta(days=1):
        raise ValueError('Evidence lifetime must be positive and at most one day.')
    issued = datetime.fromisoformat(payload['issued_at'])
    for timestamp in [issued, *(datetime.fromisoformat(item['finished_at']) for item in tests)]:
        if timestamp.tzinfo is None or timestamp > now or now - timestamp > max_age:
            raise ValueError('Evidence is stale or has an invalid completion time.')
        if timestamp > issued:
            raise ValueError('Evidence completion cannot follow issuance.')
    signature = base64.b64decode(envelope['signature'], validate=True)
    with TemporaryDirectory(prefix='test-evidence-verify-') as temporary:
        path = Path(temporary) / 'signature'
        path.write_bytes(signature)
        _ssh(['-Y', 'verify', '-f', str(allowed_signers), '-I', signer,
              '-n', NAMESPACE, '-s', str(path)], data=canonical(payload))
    return payload
