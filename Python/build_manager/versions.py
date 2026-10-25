"""Local monotonic reservations; remote uniqueness remains provider-owned."""
import json
from pathlib import Path

from .locking import workspace_lock


def next_number(path, *, existing=(), minimum=1):
    path = Path(path)
    record = json.loads(path.read_text()) if path.exists() else {'schema': 1, 'last': 0}
    if not isinstance(record, dict) or record.get('schema', 1) != 1:
        raise ValueError('Unsupported build counter schema.')
    previous = record.get('last')
    if type(previous) is not int or previous < 0 or type(minimum) is not int or minimum < 1:
        raise ValueError('Build counters require nonnegative integer history and a positive minimum.')
    existing = tuple(existing)
    if any(type(value) is not int or value < 0 for value in existing):
        raise ValueError('Existing build identifiers must be nonnegative integers.')
    return max(minimum, previous + 1, max(existing, default=0) + 1)


def reserve_number(path, *, existing=(), minimum=1, maximum, override=None):
    path = Path(path)
    with workspace_lock(path.with_suffix('.lock')):
        number = next_number(path, existing=existing, minimum=minimum)
        if override is not None:
            selected = str(override)
            if not selected.isdigit() or int(selected) < number:
                raise ValueError('Explicit build must be increasing and unused in this local workspace.')
            number = int(selected)
        if number > maximum:
            raise ValueError('Build identifier exceeds the platform limit.')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema': 1, 'last': number}) + '\n')
        temporary.replace(path)
        return number
