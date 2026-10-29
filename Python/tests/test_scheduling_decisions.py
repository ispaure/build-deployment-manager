"""Readiness and final outcomes keep dependency, cleanup and retry semantics distinct."""
from dataclasses import replace
import unittest

from build_manager.models import Phase, Plan
from build_manager.scheduling import phase_is_ready, skip_reason, final_status


def phase(name, **options):
    return Phase(name, ('fixture',), '.', **options)


class SchedulingDecisionTests(unittest.TestCase):
    def ready(self, step, **options):
        defaults = dict(running=(), pending=[step], rows={}, max_workers=2,
                        retry_after={}, now=10, cancelled=False)
        defaults.update(options)
        return phase_is_ready(step, **defaults)

    def test_completion_wait_can_follow_failure_but_success_dependency_is_skipped(self):
        failed = {'check': {'status': 'failed'}}
        completion = phase('inspect', waits_for=('check',))
        dependent = phase('build', dependencies=('check',))
        self.assertTrue(self.ready(completion, rows=failed))
        self.assertEqual(skip_reason(completion, failed, cancelled=False), '')
        self.assertTrue(self.ready(dependent, rows=failed))
        self.assertEqual(skip_reason(dependent, failed, cancelled=False), 'dependency did not pass')
        for status in ('running', 'retrying'):
            self.assertFalse(self.ready(completion, rows={'check': {'status': status}}))

    def test_cancellation_bypasses_retry_delay_but_keeps_cleanup_ownership(self):
        inspection = phase('inspect', effect='inspect', retry_exit_codes=(75,))
        cleanup = phase('cleanup', always=True)
        self.assertFalse(self.ready(inspection, retry_after={'inspect': 20}))
        self.assertTrue(self.ready(inspection, retry_after={'inspect': 20}, cancelled=True))
        self.assertEqual(skip_reason(inspection, {}, cancelled=True), 'cancelled')
        self.assertFalse(self.ready(cleanup, running=(inspection,), cancelled=True))
        self.assertFalse(self.ready(cleanup, pending=[inspection, cleanup], cancelled=True))
        self.assertTrue(self.ready(cleanup, cancelled=True))
        self.assertEqual(skip_reason(cleanup, {}, cancelled=True), '')

    def test_equivalent_evidence_producers_do_not_occupy_another_worker(self):
        first = phase('first', effect='test', reuse_key='a' * 64)
        second = replace(first, id='second')
        independent = phase('other')
        self.assertFalse(self.ready(second, running=(first,)))
        self.assertTrue(self.ready(independent, running=(first,)))

    def test_unknown_effect_and_failed_cleanup_take_precedence_over_approval(self):
        plan = Plan('Fixture', 'Check', {}, (phase('effect'), phase('review'), phase('cleanup', always=True)), '.')
        rows = dict(effect={'status': 'unknown', 'required': True},
                    review={'status': 'awaiting_review', 'required': True},
                    cleanup={'status': 'failed', 'required': True})
        self.assertEqual(final_status(plan, rows, cancelled=True), 'unknown')
        rows['effect']['status'] = 'passed'
        self.assertEqual(final_status(plan, rows, cancelled=True), 'failed')
        rows['cleanup']['status'] = 'passed'
        self.assertEqual(final_status(plan, rows, cancelled=True), 'awaiting_review')
