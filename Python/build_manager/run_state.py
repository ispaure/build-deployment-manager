"""Headless phase facts and event buffering shared by live and retained runs."""
import json
import time
from typing import Any, NotRequired, TypedDict


class PhaseFact(TypedDict):
    id: str
    status: str
    seconds: NotRequired[float | None]
    reason: NotRequired[str]
    resource: NotRequired[str]
    tests: NotRequired[list[dict[str, Any]]]
    live_tests: NotRequired[list[dict[str, Any]]]


class EventStream:
    """Keep incomplete JSON lines until the next process read."""
    def __init__(self):
        self.buffer = ''

    def append(self, text):
        self.buffer += text

    def has_line(self):
        return '\n' in self.buffer

    def take_event(self) -> dict[str, Any]:
        line, self.buffer = self.buffer.split('\n', 1)
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        return event if isinstance(event, dict) else dict(type='output', text=line)


class RunState:
    """Own measured phase facts; presentation never changes execution evidence."""
    def __init__(self, *, clock=None):
        self.clock = clock if clock is not None else lambda: time.monotonic()
        self.facts: dict[str, PhaseFact] = {}
        self.started: dict[str, float] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.outcome = ''
        self.cancelling = False

    def reset(self, phases):
        self.facts.clear()
        self.facts.update((phase.id, dict(id=phase.id, status='queued')) for phase in phases)
        self.started.clear()
        self.pending.clear()
        self.outcome = ''
        self.cancelling = False

    def queue_event(self, event: dict[str, Any]) -> str | None:
        key = event['id']
        previous = self.pending.get(key, self.facts.get(key, {})).get('status')
        self.pending.setdefault(key, {}).update(event)
        return previous

    def drain_events(self):
        events = list(self.pending.values())
        self.pending.clear()
        return events

    def update(self, event: dict[str, Any]) -> PhaseFact:
        key = event['id']
        if event['status'] != 'waiting_resource':
            event = dict(event, resource='', reason=event.get('reason', ''))
        self.facts.setdefault(key, {}).update(event)
        if event['status'] == 'running':
            self.started.setdefault(key, self.clock() - (event.get('seconds') or 0))
        else:
            self.started.pop(key, None)
        return self.facts[key]

    def snapshot(self) -> dict[str, PhaseFact]:
        now = self.clock()
        return {key: dict(fact, seconds=now - self.started[key]) if key in self.started else dict(fact)
                for key, fact in self.facts.items()}

    def complete(self, status):
        self.started.clear()
        self.cancelling = False
        self.outcome = status
