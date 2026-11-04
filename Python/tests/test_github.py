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

    def test_qualified_refs_resolve_once_in_their_explicit_family(self):
        for family in ('heads', 'tags'):
            for name in ('alpha', 'release/alpha'):
                with self.subTest(family=family, name=name):
                    self.calls.clear()
                    client = self.client()
                    ref = 'refs/' + family + '/' + name
                    self.assertEqual(client.resolve_ref(ref), self.commit)
                    self.assertEqual(client.resolve_ref(ref), self.commit)
                    path = '/repos/fixture/second-project/git/ref/' + family + '/' + name.replace('/', '%2F')
                    self.assertEqual(self.calls, [('GET', path, None)] * 2)

    def test_bare_refs_keep_branch_then_tag_fallback_but_qualified_refs_do_not(self):
        def transport(method, path, body):
            self.calls.append((method, path, body))
            if '/git/ref/heads/' in path:
                raise RuntimeError('GitHub HTTP 404')
            return {'object': {'type': 'commit', 'sha': self.commit}}
        client = GitHub('fixture/second-project', transport=transport)
        self.assertEqual(client.resolve_ref('alpha'), self.commit)
        self.assertEqual([row[1].rsplit('/', 2)[-2] for row in self.calls], ['heads', 'tags'])
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, 'not been published'):
            client.resolve_ref('refs/heads/alpha')
        self.assertEqual(self.calls, [('GET', '/repos/fixture/second-project/git/ref/heads/alpha', None)])

    def test_qualified_dispatch_still_checks_expected_commit_before_post(self):
        client = self.client()
        with self.assertRaisesRegex(ValueError, 'differs'):
            client.dispatch('checks.yml', 'refs/tags/alpha', 'b' * 40, confirmed=True)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
        self.assertEqual(client.dispatch('checks.yml', 'refs/tags/alpha', self.commit, confirmed=True), 42)
        self.assertEqual(self.calls[-1][2]['ref'], 'refs/tags/alpha')

    def test_empty_qualified_ref_is_rejected_before_request(self):
        for ref in ('', 'refs/heads/', 'refs/tags/'):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.client().resolve_ref(ref)
        self.assertEqual(self.calls, [])

    def test_accepted_dispatch_without_run_identity_is_not_retried(self):
        def transport(method, path, body):
            self.calls.append((method, path, body))
            return {'object': {'type': 'commit', 'sha': self.commit}} if method == 'GET' else {}
        client = GitHub('fixture/second-project', transport=transport)
        with self.assertRaisesRegex(RuntimeError, 'do not dispatch again'):
            client.dispatch('checks.yml', 'refs/heads/alpha', self.commit, confirmed=True)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

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


class CredentialReferenceTests(unittest.TestCase):
    def test_missing_selected_environment_never_falls_back_to_another_account(self):
        from build_manager.github import credential_token
        from unittest.mock import patch
        with patch('subprocess.run') as helper:
            with self.assertRaisesRegex(ValueError,'missing'):
                credential_token(reference='SELECTED_TOKEN',kind='environment-name',environment={})
            helper.assert_not_called()
        self.assertEqual(credential_token(reference='SELECTED_TOKEN',kind='environment-name',environment={'SELECTED_TOKEN':'synthetic'}),'synthetic')
