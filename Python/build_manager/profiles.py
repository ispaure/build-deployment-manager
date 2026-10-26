"""Non-secret profile values and explicit precedence; providers own credentials."""
import json
import os
import time
from pathlib import Path
from tempfile import mkstemp


def effective(defaults, profile=None, environment=None, overrides=None, *, variables=None):
    values = dict(defaults)
    sources = dict.fromkeys(values, 'repository default')
    for origin, incoming in [('local profile', profile or {}), ('environment',
            {key: environment[name] for key, name in (variables or {}).items()
             if environment is not None and name in environment}), ('run override', overrides or {})]:
        for name, value in incoming.items():
            if name not in defaults:
                raise ValueError('Unsupported setting: ' + name)
            expected = type(defaults[name])
            if type(value) is not expected:
                # Environment variables and text controls can supply numeric
                # values, but booleans must never use Python's truthy strings.
                if expected is int and isinstance(value, str) and value.isdecimal():
                    value = int(value)
                else:
                    raise ValueError(name + ' must be a ' + expected.__name__ + '.')
            values[name], sources[name] = value, origin
    return values, sources


def save_profile(path, values, *, allowed):
    if set(values) - set(allowed):
        raise ValueError('Unsupported profile fields.')
    from .credentials import reject_secrets
    reject_secrets(values)
    save_json(path, dict(schema=1, values=values))


def save_json(path, data):
    """Publish manager state privately; project schema and writer locks stay external."""
    encoded = json.dumps(data, indent=2) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != 'nt':
            temporary.chmod(0o600)
        # Windows readers (including child processes) can briefly deny replacement.
        # Keep publication atomic and bounded; permanent failures still propagate.
        deadline = time.monotonic() + 2
        while True:
            try:
                temporary.replace(path)
                break
            except OSError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33)
                        or time.monotonic() >= deadline):
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


def load_profile(path):
    path = Path(path)
    if not path.exists():
        return {}
    result = json.loads(path.read_text())
    if not isinstance(result, dict) or result.get('schema') != 1 or not isinstance(result.get('values'), dict):
        raise ValueError('Unsupported profile schema.')
    return result['values']
