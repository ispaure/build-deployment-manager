"""Credential material is never configuration; references remain non-secret data."""
import os
from pathlib import Path
import re


def reject_secrets(values):
    if isinstance(values, dict):
        for key, value in values.items():
            name = str(key).lower().replace('-', '_').split('.')[-1]
            if re.search(r'(^|_)(password|passwd|token|secret|private_key|api_key|client_secret)$', name):
                raise ValueError('Store protected credential references, never secret values.')
            reject_secrets(value)
    elif isinstance(values, (list, tuple)):
        for value in values:
            reject_secrets(value)
    elif isinstance(values, str):
        if (re.search(r'-----BEGIN [A-Z]', values) or
                re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,})', values) or
                re.search(r'(?i)(?:bearer\s+\S+|https?://[^/\s:@]+:[^/\s@]+@)', values)):
            raise ValueError('Credential contents cannot be saved; use a protected reference.')
        for name, secret in os.environ.items():
            if (re.search(r'(?:TOKEN|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$', name, re.I) and
                    len(secret) >= 8 and secret in values):
                raise ValueError('An inherited credential value cannot be saved; use its environment variable name.')


def protected_reference(path, checkout=None):
    """Signing/credential files must live outside source checkouts, even if ignored."""
    candidate = Path(path).expanduser().resolve()
    if checkout and candidate.is_relative_to(Path(checkout).resolve()):
        raise ValueError('Move credential files outside the project checkout, then select that protected reference.')
    if any((parent / '.git').exists() for parent in (candidate.parent, *candidate.parents)):
        raise ValueError('Credential files must be outside Git checkouts.')
    return candidate


def validate_settings_changes(rows, values, checkout=None):
    """Shared guard for isolated adapters and directly embedded project editors."""
    reject_secrets(values)
    for name, value in values.items():
        if name not in rows or rows[name].get('read_only'):
            raise ValueError('Unknown or read-only settings field: ' + name)
        row = rows[name]
        kind_name = name.removesuffix('_reference') + '_kind'
        reference_kind = values.get(kind_name, row.get('reference_kind', ''))
        credential = row.get('credential', False) or name.startswith(('auth.', 'signing.'))
        is_file = (name.startswith('signing.') or row.get('kind') == 'protected-file' or
                   '/' in str(value) or '\\' in str(value) or
                   str(value).endswith(('.json', '.p8', '.pem', '.p12', '.mobileprovision')))
        if value and value != row.get('value') and (row.get('kind') == 'protected-file' or
                (credential and row.get('kind') == 'reference' and is_file and
                 reference_kind not in {'environment-name', 'credential-helper'})):
            # Retain old pointers while editing unrelated fields. Never move,
            # copy or rewrite an existing credential file as a settings side effect.
            protected_reference(value, checkout)
