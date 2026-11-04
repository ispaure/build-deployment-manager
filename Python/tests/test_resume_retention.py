"""Pure retention decisions preserve failures and external effects across retries."""
import sys
import unittest
from build_manager import Phase, Plan
from build_manager.workflows import retained_phase_records


def phase(name, **options):
    return Phase(name, (sys.executable, '-V'), '.', **options)


def records(**statuses):
    return [dict(id=name, status=status) for name, status in statuses.items()]


class ResumeRetentionTests(unittest.TestCase):
    def test_invalidation_propagates_through_cleanup_completion_and_success_edges(self):
        plan = Plan('Fixture', 'resume', {}, (
            phase('build'), phase('cleanup', dependencies=('build',), always=True),
            phase('inspect', waits_for=('cleanup',)), phase('runtime', dependencies=('inspect',)),
            phase('runtime-cleanup', dependencies=('runtime',), always=True),
            phase('delivered', dependencies=('runtime',), effect='deploy'), phase('stable'),
        ), '.')
        previous = records(build='failed', cleanup='passed', inspect='passed', runtime='passed',
                           **{'runtime-cleanup': 'passed', 'delivered': 'passed', 'stable': 'passed'})
        retained = retained_phase_records(plan, previous)
        self.assertEqual(set(retained), {'delivered', 'stable'})
        self.assertEqual(previous[1]['status'], 'passed')

    def test_no_retry_preserves_failed_owner_and_its_cleanup(self):
        plan = Plan('Fixture', 'resume', {}, (phase('owner'), phase('cleanup', dependencies=('owner',), always=True)), '.')
        previous = records(owner='failed', cleanup='passed')
        self.assertEqual(list(retained_phase_records(plan, previous, retry_failed=False).values()), previous)

    def test_whole_workflow_cleanup_only_refreshes_when_work_is_scheduled(self):
        plan = Plan('Fixture', 'resume', {}, (phase('owner'), phase('cleanup', always=True)), '.')
        self.assertEqual(set(retained_phase_records(plan, records(owner='passed', cleanup='passed'))), {'owner', 'cleanup'})
        self.assertEqual(retained_phase_records(plan, records(owner='failed', cleanup='passed')), {})

    def test_inherited_external_effect_is_retained_without_replay(self):
        plan = Plan('Fixture', 'resume', {}, (phase('owner', effect='test'), phase('delivered', dependencies=('owner',))), '.', effect='deploy')
        self.assertEqual(set(retained_phase_records(plan, records(owner='failed', delivered='passed'))), {'delivered'})

    def test_stale_external_cleanup_fails_closed_instead_of_replaying_or_reusing_it(self):
        plan = Plan('Fixture', 'resume', {}, (
            phase('owner'), phase('remote-cleanup', dependencies=('owner',), always=True, effect='deploy'),
        ), '.')
        for status in ('passed', 'unknown'):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'External cleanup cannot'):
                retained_phase_records(plan, records(owner='failed', **{'remote-cleanup': status}))
