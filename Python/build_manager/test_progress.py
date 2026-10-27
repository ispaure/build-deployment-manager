"""Bounded, advisory test-runner events; never execution or release evidence."""
import json
import math
import os

PREFIX = '@@BUILD_MANAGER_TEST@@'


def emit_test_progress(kind, **fields):
    """Project runners opt in through the owning executor's environment."""
    if os.environ.get('BUILD_MANAGER_TEST_PROGRESS') == '1':
        if isinstance(fields.get('message'), str):
            fields['message'] = fields['message'][:2000]
        line = PREFIX + json.dumps(dict(schema=1, kind=kind, **fields))
        if parse_test_progress(line) is not None:
            print('\n' + line, flush=True)


def parse_test_progress(line):
    if not line.startswith(PREFIX) or len(line) > 16384:
        return None
    try:
        event = json.loads(line[len(PREFIX):])
        if not isinstance(event, dict) or event.get('schema') != 1:
            return None
        kind = event.get('kind')
        if kind not in {'file_started', 'file_finished', 'test_started', 'test_finished'}:
            return None
        result = dict(kind=kind)
        for key in ('name', 'classname', 'file', 'message'):
            value = event.get(key, '')
            if not isinstance(value, str) or len(value) > (8000 if key == 'message' else 1000):
                return None
            result[key] = value
        if not result['name']:
            return None
        if kind.endswith('finished'):
            if event.get('status') not in {'passed', 'failed', 'error', 'skipped', 'timeout', 'crashed'}:
                return None
            result['status'] = event['status']
            seconds = event.get('seconds')
            if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0):
                return None
            result['seconds'] = seconds
        return result
    except (ValueError, TypeError):
        return None
