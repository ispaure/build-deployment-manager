"""Compact run events recover advisory inventory without changing execution evidence."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan
from build_manager.api import run_plan
from build_manager.event_stream import CHECKPOINT_SECONDS, CompactEvents, ExpandEvents, ROWS_PER_FRAME
from build_manager.run_state import RunEventLineBuffer
from build_manager.test_results import read_junit


def progress(files, cases, phase='work'):
    return dict(type='phase', id=phase, status='running', tests_provisional=True,
                test_files=files, live_tests=cases)


class EventStreamTests(unittest.TestCase):
    def test_frames_are_bounded_and_reconstruct_updates_removals_and_empty_inventories(self):
        encoder, decoder = CompactEvents(), ExpandEvents()
        cases = [dict(name=f'case-{index}', status='passed') for index in range(2 * ROWS_PER_FRAME)]
        files = [dict(name='cases.py')]
        first, edited, shortened, empty = (progress(files, cases),
            progress(files, [dict(cases[0], status='failed'), *cases[1:]]),
            progress([], cases[-3:]), progress([], []))
        for index, source in enumerate((first, edited, shortened, empty)):
            with self.subTest(index=index):
                frames = list(encoder.encode(source))
                updates = [frame for frame in frames if 'rows' in frame]
                self.assertTrue(all(len(frame['rows']) <= ROWS_PER_FRAME for frame in updates))
                if index == 1:
                    self.assertEqual(sum(len(frame['rows']) for frame in updates), 1)
                replay = [decoder.apply(json.loads(json.dumps(frame))) for frame in frames]
                self.assertEqual(replay, [None] * (len(frames) - 1) + [source])

    def test_gap_and_late_attachment_recover_from_checkpoint_without_affecting_another_phase(self):
        now = 0
        encoder = CompactEvents(clock=lambda: now)
        decoder, attached = ExpandEvents(), ExpandEvents()
        first = progress([], [dict(name='one')])
        second = progress([], [dict(name='one'), dict(name='two')])
        other = progress([dict(name='other.py')], [], phase='other')
        for frame in encoder.encode(first):
            decoder.apply(frame)
        self.assertEqual([decoder.apply(frame) for frame in encoder.encode(other)][-1], other)
        lost = list(encoder.encode(second))
        self.assertIsNone(decoder.apply(lost[-1]))
        self.assertIsNone(attached.apply(lost[-1]))
        now = CHECKPOINT_SECONDS - 1
        self.assertIsNone([decoder.apply(frame) for frame in encoder.encode(second)][-1])
        self.assertEqual([decoder.apply(frame) for frame in encoder.encode(other)][-1], other)
        now += 1
        checkpoint = list(encoder.encode(second))
        self.assertTrue(checkpoint[0]['checkpoint'])
        self.assertEqual([decoder.apply(frame) for frame in checkpoint][-1], second)
        self.assertEqual([attached.apply(frame) for frame in checkpoint][-1], second)
        # The independent terminal event still arrives even if the observer
        # misses every live inventory record.
        finished = dict(type='phase', id='work', status='failed', tests=[dict(name='actual')])
        self.assertIs(ExpandEvents().apply(finished), finished)

    def test_ui_line_buffer_handles_fragmentation_and_resume_generation(self):
        encoder = CompactEvents()
        stream = RunEventLineBuffer()
        old = progress([], [dict(name='old')])
        frames = list(encoder.encode(old))

        def push(frame):
            line = json.dumps(frame) + '\n'
            stream.append(line[:12])
            self.assertFalse(stream.has_line())
            stream.append(line[12:])
            self.assertTrue(stream.has_line())
            return stream.take_event()

        self.assertEqual([push(frame) for frame in frames][-1], old)
        fresh = progress([], [])
        fresh['_test_inventory_reset'] = True
        reset = list(encoder.encode(fresh))
        self.assertNotEqual(frames[0]['stream'], reset[0]['stream'])
        self.assertEqual([push(frame) for frame in reset][-1], progress([], []))
        self.assertEqual(push(dict(type='phase', id='work', status='cancelled'))['status'], 'cancelled')


SCRIPT = """
import os
from pathlib import Path
import signal
import sys
import time
from build_manager.reporting import write_junit
from build_manager.test_progress import emit_test_progress as emit

root, outcome = Path(sys.argv[1]), sys.argv[2]
case = dict(name='last', classname='Checks', file='cases.py', stage='smoke',
            status='failed' if outcome == 'failed' else 'passed',
            seconds=.125, message='token=' + os.environ['FIXTURE_VALUE'])
emit('file_started', name='cases.py')
emit('test_started', name='last', classname='Checks', file='cases.py')
emit('test_finished', **case)
emit('file_finished', name='cases.py', status=case['status'], seconds=.25)
if outcome == 'cancelled':
    (root / 'worker.pid').write_text(str(os.getpid()))
    time.sleep(30)
if outcome == 'crashed':
    if os.name == 'nt':
        os._exit(17)
    os.kill(os.getpid(), signal.SIGKILL)
write_junit(root / 'data.xml', 'fixture', [dict(case, message='failure detail')])
raise SystemExit(3 if outcome == 'failed' else 0)
"""


class TransportExecutionTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ['MANAGER_TEST_SCRATCH']) if 'MANAGER_TEST_SCRATCH' in os.environ else None
        temp = TemporaryDirectory(dir=scratch)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.secret = 'føcused-credential"escaped'

    def plan(self, outcome):
        report = self.root / 'data.xml'
        source = Path(__file__).resolve().parents[1]
        phase = Phase('run-checks', (sys.executable, '-c', SCRIPT, str(self.root), outcome),
                      str(self.root), environment=dict(PYTHONPATH=str(source)),
                      test_files=('cases.py',), artifacts=(str(report),),
                      artifact_types={str(report): 'junit'}, kind='test', timeout=10)
        cleanup = Phase('cleanup', (sys.executable, '-c',
            'from pathlib import Path; Path("cleanup-ran").touch()'),
            str(self.root), always=True, dependencies=('run-checks',))
        return Plan('Fixture', 'Test', {}, (phase, cleanup), str(self.root / 'workspace'),
                    secret_environment=('FIXTURE_VALUE',))

    def execute_cli(self, outcome, *, compact):
        plan_path = self.root / 'selected.json'
        self.plan(outcome).save(plan_path)
        output = self.root / (outcome + ('-compact' if compact else '-snapshot'))
        command = [sys.executable, '-m', 'build_manager.cli', '--registry', str(self.root / 'registry'),
                   'run', str(plan_path), '--output', str(output), '--events']
        if compact:
            command += ['--event-format', 'compact']
        environment = dict(os.environ, FIXTURE_VALUE=self.secret)
        completed = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0 if outcome == 'passed' else 1, completed.stderr)
        self.assertNotIn(self.secret, completed.stdout)
        self.assertNotIn('credential', completed.stdout)
        records = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(all(record['cli_schema'] == 1 for record in records))
        self.assertEqual(records[-1]['status'], outcome)
        events = [record['event'] for record in records[:-1]]
        self.assertEqual(any(event['type'] == 'test_inventory' for event in events), compact)
        decoder = ExpandEvents()
        events = [event for frame in events if (event := decoder.apply(frame)) is not None]
        self.assertTrue(any(event.get('current_test', {}).get('name') == 'last'
                            for event in events if event.get('current_test')))
        row = json.loads((output / 'result.json').read_text())['phases'][0]
        self.assertEqual(next(event['tests'] for event in events if event.get('tests')), row['tests'])
        self.assertEqual(row['tests'][0]['file'], 'cases.py')
        self.assertEqual(row['tests'][0]['seconds'], .125)
        artifact = Path(row['artifacts'][0]['path'])
        self.assertEqual(artifact.read_bytes(), (self.root / 'data.xml').read_bytes())
        self.assertEqual(read_junit(artifact)[0]['status'], outcome)
        return row['tests'], artifact.read_bytes()

    def test_public_cli_legacy_and_compact_retain_equal_failure_and_junit(self):
        for outcome in ('passed', 'failed'):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.execute_cli(outcome, compact=False),
                                 self.execute_cli(outcome, compact=True))

    def test_python_api_cancelled_and_crashed_worker_keep_provisional_cases_and_cleanup(self):
        for outcome in ('cancelled', 'crashed'):
            with self.subTest(outcome=outcome):
                cancelled = Event()
                decoder = ExpandEvents()
                events = []

                def observe(frame):
                    event = decoder.apply(frame)
                    if event is not None:
                        events.append(event)
                        if outcome == 'cancelled' and event.get('live_tests'):
                            cancelled.set()

                plan = self.plan(outcome)
                output = self.root / outcome
                with patch.dict(os.environ, {'FIXTURE_VALUE': self.secret}):
                    report = run_plan(plan, output, cancelled=cancelled, event=observe, event_format='compact')
                row = report['phases'][0]
                self.assertEqual(report['status'], 'cancelled' if outcome == 'cancelled' else 'failed')
                self.assertTrue(any(event.get('live_tests') for event in events))
                self.assertIsNone(row['current_test'])
                if outcome == 'crashed':
                    self.assertEqual(row['exit_code'], 17 if os.name == 'nt' else -signal.SIGKILL)
                    self.assertFalse(row['tests_provisional'])
                    self.assertEqual(row['live_tests'], [])
                else:
                    self.assertEqual(row['live_tests'][0]['name'], 'last')
                    self.assertTrue(row['tests_provisional'])
                self.assertFalse(row.get('tests'))
                self.assertEqual(report['phases'][1]['status'], 'passed')
                self.assertTrue((self.root / 'cleanup-ran').exists())
                (self.root / 'cleanup-ran').unlink()
                self.assertNotIn('credential', json.dumps(events))

    def test_new_observer_gets_idle_checkpoint_before_work_continues(self):
        cancelled = Event()
        decoder = ExpandEvents()

        def observe(frame):
            if frame.get('sequence', 0) > 1 and frame.get('checkpoint'):
                live['checkpoint'] = frame['sequence']
            if live.get('checkpoint'):
                event = decoder.apply(frame)
                if event and event.get('live_tests'):
                    live['event'] = event
                    cancelled.set()

        live = {}
        output = self.root / 'idle'
        plan = self.plan('cancelled')
        with patch('build_manager.executor.CHECKPOINT_SECONDS', .25), \
                patch.dict(os.environ, {'FIXTURE_VALUE': self.secret}):
            report = run_plan(plan, output, cancelled=cancelled, event=observe, event_format='compact')
        self.assertEqual(report['status'], 'cancelled')
        restored = live['event']
        self.assertEqual(restored['live_tests'][0]['name'], 'last')
        self.assertEqual(restored['test_files'][0]['name'], 'cases.py')
        self.assertEqual(restored['log'], 'run-checks.log')
        self.assertTrue((self.root / 'worker.pid').is_file())


if __name__ == '__main__':
    unittest.main()
