"""Concurrency fixtures keep strict interval checks when wall-clock samples coincide."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from process_rendezvous import rendezvous_argv
from test_journeys import integrated
import test_scheduler as scheduler_fixtures


class ProcessIntervalClockTests(unittest.TestCase):
    def test_every_emitted_interval_uses_the_same_integer_high_resolution_clock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'peer.started').touch()
            scheduler = scheduler_fixtures.SchedulerTests('test_independent_branches_overlap_and_dependency_waits')
            scheduler.root = root
            samples = (
                ('rendezvous', rendezvous_argv(root, 'rendezvous', 'peer')[-1]),
                ('c', scheduler.phase('c').argv[-1]),
                ('firebase', next(phase for phase in integrated(root).phases if phase.id == 'firebase').argv[-1]),
            )
            for index, (name, code) in enumerate(samples):
                with self.subTest(source=name):
                    start, end = 1000 + index * 10, 1001 + index * 10
                    clock = SimpleNamespace(time=Mock(return_value=42.0),
                        perf_counter_ns=Mock(side_effect=[start, end]),
                        monotonic=Mock(return_value=0), sleep=Mock())
                    with patch.dict('sys.modules', {'time': clock}):
                        exec(code, {})
                    values = json.loads((root/(name+'.json')).read_text())
                    self.assertEqual(values, [start, end])
                    self.assertTrue(all(type(value) is int for value in values))
                    self.assertLess(*values)
                    clock.time.assert_not_called()
                    self.assertEqual(clock.perf_counter_ns.call_count, 2)

    def test_rendezvous_still_rejects_serial_admission_without_peer(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            clock = SimpleNamespace(time=Mock(return_value=42.0), perf_counter_ns=Mock(return_value=1000),
                                    monotonic=Mock(side_effect=[0, 6]), sleep=Mock())
            with patch.dict('sys.modules', {'time': clock}), self.assertRaisesRegex(RuntimeError, 'not admitted concurrently'):
                exec(rendezvous_argv(root, 'alone', 'missing')[-1], {})
            self.assertTrue((root/'alone.started').is_file())
            self.assertFalse((root/'alone.json').exists())
