"""Advisory case events cannot complete a phase or replace final test evidence."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager import Executor, Phase, Plan
from build_manager.test_progress import PREFIX, parse_test_progress


class TestProgressTests(unittest.TestCase):
    def test_events_are_bounded_and_cannot_override_execution_fields(self):
        event = dict(schema=1, kind='test_started', name='test_one', file='test_shared.py',
                     stage='smoke', status='passed', id='other-phase', artifacts=['unexpected'])
        parsed = parse_test_progress(PREFIX + json.dumps(event))
        self.assertEqual(parsed['name'], 'test_one')
        self.assertEqual(parsed['stage'], 'smoke')
        for key in ('status', 'id', 'artifacts'):
            self.assertNotIn(key, parsed)
        for invalid in ('ordinary output', PREFIX + 'broken', PREFIX + '[]',
                        PREFIX + json.dumps(dict(event, schema=9)),
                        PREFIX + json.dumps(dict(event, stage='urgent')),
                        PREFIX + json.dumps(dict(event, stage=[])),
                        PREFIX + json.dumps(dict(event, name='x' * 1001)),
                        PREFIX + json.dumps(dict(event, kind='test_finished', seconds=-1)),
                        PREFIX + json.dumps(dict(event, kind='test_finished', seconds=float('nan')))):
            self.assertIsNone(parse_test_progress(invalid))

    def test_current_test_is_received_before_it_finishes_and_retains_file_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release, report = root / 'release', root / 'cases.xml'
            code = f'''import time
from pathlib import Path
from build_manager.test_progress import emit_test_progress
from build_manager.reporting import write_junit
emit_test_progress('file_started', name='test_shared.py', stage='smoke')
emit_test_progress('test_started', name='test_slow', classname='Shared.Cases', file='test_shared.py', stage='smoke')
deadline = time.monotonic() + 5
while not Path({str(release)!r}).exists():
    assert time.monotonic() < deadline, 'Current test was not received before it finished'
    time.sleep(.01)
emit_test_progress('test_finished', name='test_slow', classname='Shared.Cases', file='test_shared.py', status='passed', seconds=.2, stage='smoke')
emit_test_progress('file_finished', name='test_shared.py', status='passed', seconds=.4, stage='smoke')
write_junit({str(report)!r}, 'shared', [dict(name='test_slow', classname='Shared.Cases', status='passed', seconds=.2, stage='smoke')])
'''
            phase = Phase('commonutils', (sys.executable, '-c', code), directory,
                environment=dict(PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                test_files=('test_shared.py',), artifacts=(str(report),), artifact_types={str(report): 'junit'})
            events = []
            def observe(event):
                events.append(event)
                if event.get('current_test'):
                    self.assertEqual(event['status'], 'running')
                    self.assertEqual(event['current_test']['name'], 'test_slow')
                    self.assertEqual(event['current_test']['stage'], 'smoke')
                    self.assertNotIn('tests', event)
                    release.touch()
            plan = Plan('Fixture', 'Test', {}, (phase,), str(root / 'workspace'))
            self.assertEqual(Plan.from_data(plan.data()).phases[0].test_files, ('test_shared.py',))
            result = Executor(event=observe).run(plan, root / 'result')
            self.assertTrue(release.exists())
            fact = result['phases'][0]
            self.assertEqual(fact['status'], 'passed', fact)
            self.assertIsNone(fact['current_test'])
            self.assertFalse(fact['tests_provisional'])
            self.assertEqual(fact['tests'][0]['file'], 'test_shared.py')
            self.assertEqual(fact['tests'][0]['stage'], 'smoke')
            self.assertEqual(fact['test_files'][0]['stage'], 'smoke')
            self.assertEqual(fact['test_files'][0]['seconds'], .4)
            self.assertTrue(any(event.get('live_tests') for event in events))

    def test_empty_inventory_preserves_legacy_serialized_contract(self):
        plan = Plan('Fixture', 'Test', {}, (Phase('test', (sys.executable, '-V'), '.'),), '.')
        self.assertNotIn('test_files', plan.data()['phases'][0])
        data = plan.data()
        data['phases'][0]['test_files'] = 'not a list'
        with self.assertRaises(ValueError):
            Plan.from_data(data)
