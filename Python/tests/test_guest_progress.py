"""Advisory waiting updates cannot become passes or delay owned cancellation."""
import unittest

from build_manager.guest_progress import GuestHeartbeat


class GuestProgressTests(unittest.TestCase):
    def test_waiting_is_throttled_but_reconciliation_change_is_immediate(self):
        rows = []
        current = [10]
        heartbeat = GuestHeartbeat(rows.append, 10, clock=lambda: current[0])
        heartbeat.emit('waiting')
        current[0] = 39
        heartbeat.emit('waiting')
        self.assertEqual(len(rows), 1)
        current[0] = 40
        heartbeat.emit('waiting')
        self.assertEqual(rows[-1], dict(state='waiting', seconds=30))
        current[0] = 41
        heartbeat.emit('reconciling')
        self.assertEqual(rows[-1], dict(state='reconciling', seconds=31))
        self.assertEqual(set(rows[-1]), {'state', 'seconds'})

    def test_failed_or_absent_presenter_does_not_change_worker_control(self):
        def failed(_):
            raise RuntimeError('Presenter closed')
        GuestHeartbeat(failed, 0, clock=lambda: 1).emit('waiting')
        def unavailable_clock():
            self.fail('No presenter needs no polling')
        GuestHeartbeat(None, 0, clock=unavailable_clock).emit('waiting')
