"""Partial delivery guidance keeps failed and unknown branches explicit."""
from copy import deepcopy
import unittest

from build_manager.continuation_actions import continuation_guidance, continuation_label


class ContinuationActionTests(unittest.TestCase):
    def report(self):
        return dict(status='failed', plan_identity='a' * 64, phases=[
            dict(id='android-check', status='failed', effect='test'),
            dict(id='android-delivery', status='skipped', effect='upload'),
            dict(id='ios-ready', status='awaiting_review', effect='upload'),
            dict(id='other-delivered', status='passed', effect='deploy')])

    def test_partial_delivery_is_visible_without_changing_aggregate_or_inputs(self):
        report = self.report(); before = deepcopy(report)
        guidance = continuation_guidance(report, '/tmp/retained run')
        self.assertEqual(guidance['completed_actions'], ['other-delivered'])
        self.assertEqual(guidance['pending_actions'], ['ios-ready'])
        self.assertEqual(guidance['failed_steps'], ['android-check', 'android-delivery'])
        self.assertEqual(continuation_label(report), 'Continue ready delivery…')
        action = next(row for row in guidance['next_actions'] if row['id'] == 'continue-ready')
        self.assertEqual(action['argv'][-2:], ['--approve-step', 'ios-ready'])
        self.assertIn('--no-retry-failed', action['argv'])
        self.assertNotIn('android-delivery', action['argv'])
        self.assertEqual(report, before)

    def test_unknown_action_is_never_suggested_for_approval(self):
        report = self.report(); report['phases'][0]['status'] = 'unknown'
        report['status'] = 'unknown'
        self.assertEqual(continuation_label(report), 'Continue independent steps…')
        guidance = continuation_guidance(report, '/tmp/run')
        self.assertEqual(guidance['unknown_steps'], ['android-check'])
        self.assertIn('reconciliation', guidance['warning'])
        self.assertTrue(all('android-check' not in row['argv'] for row in guidance['next_actions']))

    def test_retired_and_active_runs_offer_no_execution_actions(self):
        for changes in [dict(retirement={'reason': 'retired'}), dict(status='running'), dict(status='queued')]:
            report = self.report(); report.update(changes)
            self.assertEqual(continuation_guidance(report, '/tmp/run')['next_actions'], [])
