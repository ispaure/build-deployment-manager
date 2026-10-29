"""Run snapshots and partial events retain measured evidence across UI refreshes."""
from types import SimpleNamespace
import unittest

from build_manager.run_state import EventStream, RunState


class RunStateTests(unittest.TestCase):
    def test_partial_events_merge_before_publication_and_keep_start_time(self):
        now = [100.0]
        state = RunState(clock=lambda: now[0])
        state.reset([SimpleNamespace(id='checks')])
        self.assertEqual(state.queue_event(dict(id='checks', status='running', tests=[{'name': 'first'}], seconds=2)), 'queued')
        self.assertEqual(state.queue_event(dict(id='checks', status='running', current_test={'name': 'second'})), 'running')
        self.assertEqual(state.facts['checks']['status'], 'queued')
        for event in state.drain_events():
            state.update(event)
        now[0] = 105
        state.update(dict(id='checks', status='running', current_test=None))
        snapshot = state.snapshot()['checks']
        self.assertEqual(snapshot['seconds'], 7)
        self.assertEqual(snapshot['tests'], [{'name': 'first'}])
        self.assertFalse(state.pending)
        state.update(dict(id='checks', status='passed', seconds=8))
        now[0] = 200
        self.assertEqual(state.snapshot()['checks']['seconds'], 8)
        self.assertFalse(state.started)

    def test_resource_wait_is_cleared_and_retained_measurement_does_not_tick(self):
        state = RunState(clock=lambda: 50)
        state.update(dict(id='checks', status='waiting_resource', reason='busy', resource='device'))
        state.update(dict(id='checks', status='passed', seconds=3, reused=True))
        fact = state.snapshot()['checks']
        self.assertEqual((fact['reason'], fact['resource'], fact['seconds']), ('', '', 3))
        fact['seconds'] = 100
        self.assertEqual(state.facts['checks']['seconds'], 3)

    def test_reset_discards_pending_updates_and_terminal_state(self):
        state = RunState()
        state.queue_event(dict(id='old', status='running'))
        state.complete('failed')
        state.cancelling = True
        state.reset([SimpleNamespace(id='new')])
        self.assertEqual(state.facts, {'new': {'id': 'new', 'status': 'queued'}})
        self.assertFalse(state.pending or state.started or state.outcome or state.cancelling)

    def test_json_lines_wait_for_completion_and_plain_output_survives(self):
        stream = EventStream()
        stream.append('{"type":"phase", "id":"checks",')
        self.assertFalse(stream.has_line())
        stream.append('"status":"passed"}\nplain text\n[1, 2]\ntrailing')
        self.assertEqual(stream.take_event()['status'], 'passed')
        self.assertEqual(stream.take_event(), {'type': 'output', 'text': 'plain text'})
        self.assertEqual(stream.take_event(), {'type': 'output', 'text': '[1, 2]'})
        self.assertFalse(stream.has_line())
        self.assertEqual(stream.buffer, 'trailing')
