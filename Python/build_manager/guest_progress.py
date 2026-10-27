"""Throttled advisory transport heartbeats, never guest execution evidence."""
import time


class GuestHeartbeat:
    def __init__(self, callback, started, *, interval=30, clock=None):
        self.callback, self.started, self.interval = callback, started, interval
        self.clock = clock or time.monotonic
        self.last = None
        self.state = None

    def emit(self, state):
        if self.callback is None:
            return
        now = self.clock()
        if self.last is not None and state == self.state and now - self.last < self.interval:
            return
        self.last, self.state = now, state
        try:
            self.callback(dict(state=state, seconds=max(0, now - self.started)))
        except Exception:
            # A status presenter must not change the worker's actual outcome or
            # interrupt owned cancellation/receipt reconciliation.
            pass
