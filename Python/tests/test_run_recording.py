"""Retained reports preserve attempt history, timing and redaction."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_manager.run_recording import RunRecorder


class RunRecordingTests(unittest.TestCase):
    def test_resume_accumulates_measured_time_and_keeps_previous_attempt(self):
        report = dict(status='failed', seconds=4, attempts=[{'status': 'failed'}])
        now = [10]
        with TemporaryDirectory() as directory:
            recorder = RunRecorder(Path(directory), report, (), resume=True, clock=lambda: now[0])
            now[0] = 13
            report['status'] = 'passed'
            recorder.finish_timing(retry_failed=False)
            recorder.save()
            saved = json.loads((Path(directory) / 'result.json').read_text())
        self.assertEqual(saved['seconds'], 7)
        self.assertEqual(saved['attempt_seconds'], 3)
        self.assertEqual(saved['attempts'][0], {'status': 'failed'})
        self.assertEqual(saved['attempts'][1]['status'], 'passed')
        self.assertIs(saved['attempts'][1]['retry_failed'], False)

    def test_each_save_redacts_independent_values_without_mutating_report(self):
        secret = 'synthetic-sensitive-token-123456'
        report = dict(status='unknown', phases=[{'error': secret}], source={'value': secret})
        with TemporaryDirectory() as directory, patch.dict('os.environ', BDM_FIXTURE_SECRET=secret):
            recorder = RunRecorder(Path(directory), report, ('BDM_FIXTURE_SECRET',))
            recorder.save()
            encoded = (Path(directory) / 'result.json').read_text()
        self.assertNotIn(secret, encoded)
        self.assertEqual(report['source']['value'], secret)

    def test_invalid_retained_timing_is_rejected(self):
        for seconds in (-1, True, float('nan')):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                RunRecorder(Path('.'), {'seconds': seconds}, (), resume=True)
