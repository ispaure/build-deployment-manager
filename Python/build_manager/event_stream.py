"""Versioned, advisory inventory transport shared by the CLI, API and UI."""
from itertools import batched
from threading import Lock
import time
from uuid import uuid4


EVENT_FORMATS = ('snapshot', 'compact')
INVENTORIES = ('test_files', 'live_tests')
CHECKPOINT_SECONDS = 60
ROWS_PER_FRAME = 64


def resets_inventory(event):
    return event.get('status') != 'running' or ('started_at' in event and 'tests_provisional' not in event)


class CompactEvents:
    """Encode running inventories, leaving lifecycle and final evidence intact."""

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.phases = {}

    def encode(self, event):
        if event['type'] != 'phase':
            yield event
            return
        phase = event['id']
        reset = event.get('_test_inventory_reset', False)
        if reset or resets_inventory(event):
            self.phases.pop(phase, None)
        if reset:
            event = dict(event)
            event.pop('_test_inventory_reset')
        force_checkpoint = event.get('_test_inventory_checkpoint', False)
        fields = [key for key in INVENTORIES if key in event]
        if event['status'] != 'running' or not fields:
            yield event
            return

        generation, sequence, deadline, previous = self.phases.get(phase, (None, 0, 0, {}))
        now = self.clock()
        snapshot = generation is None or force_checkpoint or now >= deadline
        checkpoint = snapshot
        if snapshot:
            deadline = now + CHECKPOINT_SECONDS
        if generation is None:
            generation = uuid4().hex
        inventories = dict(previous, **{key: event[key] for key in fields})

        def frame(**data):
            nonlocal sequence, checkpoint
            sequence += 1
            result = dict(type='test_inventory', progress_schema=1, id=phase, stream=generation,
                          sequence=sequence, checkpoint=checkpoint, **data)
            checkpoint = False
            return result

        for key in inventories if snapshot else fields:
            rows = inventories[key]
            old = () if snapshot else previous.get(key, ())
            changes = ((index, row) for index, row in enumerate(rows)
                       if index >= len(old) or row != old[index])
            for batch in batched(changes, ROWS_PER_FRAME):
                yield frame(field=key, rows=batch)
        yield frame(sizes={key: len(rows) for key, rows in inventories.items()},
                    phase={key: value for key, value in event.items()
                           if key not in INVENTORIES and key != '_test_inventory_checkpoint'},
                    fields=fields)
        self.phases[phase] = (generation, sequence, deadline, inventories)


def event_callback(callback, event_format):
    if event_format not in EVENT_FORMATS:
        raise ValueError('Unknown run event format: ' + str(event_format))
    if event_format == 'snapshot' or callback is None:
        return callback
    encoder = CompactEvents()
    lock = Lock()

    def relay(event):
        with lock:
            for frame in encoder.encode(event):
                callback(frame)

    return relay


class ExpandEvents:
    """Rebuild snapshot events. A checkpoint repairs dropped frames or late attachment."""

    def __init__(self):
        self.phases = {}

    def apply(self, frame):
        if frame.get('type') != 'test_inventory':
            if frame.get('type') == 'finished':
                self.phases.clear()
            if frame.get('type') == 'phase' and resets_inventory(frame):
                self.phases.pop(frame.get('id'), None)
            return frame
        phase, stream, sequence = (frame.get(key) for key in ('id', 'stream', 'sequence'))
        if not isinstance(phase, str):
            return None
        if (type(frame.get('progress_schema')) is not int or frame['progress_schema'] != 1
                or not isinstance(stream, str) or type(sequence) is not int or sequence < 1):
            self.phases.pop(phase, None)
            return None
        previous_stream, previous_sequence, inventories = self.phases.get(phase, (None, 0, None))
        if inventories is not None and stream == previous_stream and sequence <= previous_sequence:
            return None
        if frame.get('checkpoint') is True:
            inventories = {}
        elif inventories is None or stream != previous_stream or sequence != previous_sequence + 1:
            self.phases[phase] = (stream, sequence, None)
            return None
        try:
            if 'field' in frame:
                field, rows = frame['field'], frame['rows']
                if field not in INVENTORIES or not isinstance(rows, (list, tuple)) or len(rows) > ROWS_PER_FRAME:
                    raise ValueError('Invalid inventory frame.')
                inventory = inventories.setdefault(field, {})
                for index, row in rows:
                    if type(index) is not int or index < 0 or not isinstance(row, dict):
                        raise ValueError('Invalid inventory row.')
                    inventory[index] = row
                event = None
            else:
                event = self._snapshot(frame, inventories)
        except (KeyError, TypeError, ValueError):
            self.phases.pop(phase, None)
            return None
        self.phases[phase] = (stream, sequence, inventories)
        return event

    @staticmethod
    def _snapshot(frame, inventories):
        event, sizes, fields = frame['phase'], frame['sizes'], frame['fields']
        if (not isinstance(event, dict) or event.get('type') != 'phase'
                or event.get('id') != frame['id'] or event.get('status') != 'running'
                or not isinstance(sizes, dict) or not isinstance(fields, list)
                or any(key not in sizes for key in fields)):
            raise ValueError('Invalid inventory commit.')
        event = dict(event)
        for key, size in sizes.items():
            inventory = inventories.setdefault(key, {})
            if key not in INVENTORIES or type(size) is not int or size < 0:
                raise ValueError('Incomplete inventory.')
            if len(inventory) > size:
                for index in tuple(inventory):
                    if index >= size:
                        del inventory[index]
            if len(inventory) != size:
                raise ValueError('Incomplete inventory.')
            if key in fields:
                event[key] = [inventory[index] for index in range(size)]
        return event
