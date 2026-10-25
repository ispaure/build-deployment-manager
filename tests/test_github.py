"""Controlled GitHub transport: no live dispatch, upload or notification."""
from threading import Event
import unittest

from build_manager.github import GitHub


class GitHubContractTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.commit = 'a' * 40

    def transport(self, method, path, body):
        self.calls.append((method, path, body))
        if '/git/ref/' in path:
            return {'object': {'type': 'commit', 'sha': self.commit}}
        if path.endswith('/dispatches'):
            return {'workflow_run_id': 42}
        return dict(status='completed', conclusion='success', head_sha=self.commit)

    def client(self):
        return GitHub('fixture/second-project', transport=self.transport)

    def test_declined_confirmation_sends_nothing(self):
        with self.assertRaises(ValueError):
            self.client().dispatch('checks.yml', 'main', self.commit)
        self.assertEqual(self.calls, [])

    def test_mismatched_ref_blocks_write_and_success_is_tied_to_exact_run(self):
        client = self.client()
        with self.assertRaises(ValueError):
            client.dispatch('checks.yml', 'main', 'b' * 40, confirmed=True)
        self.assertFalse(any(call[0] == 'POST' for call in self.calls))
        run = client.dispatch('checks.yml', 'main', self.commit, {'platform': 'test'}, confirmed=True)
        self.assertEqual(run, 42)
        self.assertEqual(client.wait(run, self.commit)['conclusion'], 'success')

    def test_cancellation_targets_only_the_owned_run(self):
        cancelled = Event()
        cancelled.set()
        result = self.client().wait(42, self.commit, cancelled=cancelled)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.calls, [('POST', '/repos/fixture/second-project/actions/runs/42/cancel', None)])

    def test_failed_and_wrong_source_results_are_not_passes(self):
        for result in (dict(status='completed', conclusion='failure', head_sha=self.commit),
                       dict(status='completed', conclusion='success', head_sha='b' * 40)):
            client = GitHub('fixture/second-project', transport=lambda *args: result)
            with self.assertRaises((RuntimeError, ValueError)):
                client.wait(42, self.commit)
