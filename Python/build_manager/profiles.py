"""Non-secret profile values and explicit precedence; providers own credentials."""
import json
import os
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
    encoded = json.dumps(dict(schema=1, values=values), indent=2) + '\n'
    if '-----BEGIN ' in encoded or any(name.lower() in {'password', 'token', 'private_key'} for name in values):
        raise ValueError('Profiles store credential references, never secret contents.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    # Each writer has its own private temporary; replacement stays atomic.
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != 'nt':
            temporary.chmod(0o600)
        temporary.replace(path)
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
