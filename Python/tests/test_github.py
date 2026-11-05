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


class Clock:
    def __init__(self): self.now = 0
    def read(self): return self.now
    def is_set(self): return False
    def wait(self, seconds): self.now += seconds


class GitHubAttemptTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.calls = Clock(), []
        self.commit = 'a' * 40
        self.binding = dict(expected_ref='refs/tags/v1.0-alpha.1', expected_workflow='release.yml')

    def row(self, attempt=2, status='queued', conclusion=None):
        return dict(id=42, run_attempt=attempt, head_sha=self.commit, head_branch='v1.0-alpha.1',
                    path='.github/workflows/release.yml', repository={'full_name':'fixture/repo'},
                    status=status, conclusion=conclusion)

    def client(self, action):
        def transport(method,path,body):
            self.calls.append((method,path,body))
            return action(method,path,body)
        return GitHub('fixture/repo',transport=transport,clock=self.clock.read)

    def test_exact_attempt_wait_ignores_stale_parent_and_observes_running_before_success(self):
        states=iter([self.row(),self.row(status='in_progress'),self.row(status='completed',conclusion='success')])
        def action(method,path,body):
            self.assertTrue(path.endswith('/attempts/2'))
            return next(states)
        result=self.client(action).wait_attempt(42,2,self.commit,**self.binding,timeout=5,poll=1,cancelled=self.clock)
        self.assertEqual(result['conclusion'],'success')
        self.assertEqual(self.clock.now,2)
        self.assertTrue(all(method=='GET' for method,_,_ in self.calls))

    def test_queued_exact_attempt_never_invents_success_from_missing_job_witness(self):
        with self.assertRaises(TimeoutError):
            self.client(lambda *args:self.row()).wait_attempt(42,2,self.commit,**self.binding,
                timeout=2,poll=1,cancelled=self.clock)
        self.assertEqual(self.clock.now,2)

    def test_wrong_attempt_source_ref_workflow_and_repository_fail_without_write(self):
        for field,value in [('id',43),('run_attempt',3),('head_sha','b'*40),('head_branch','main'),
                            ('path','.github/workflows/other.yml'),('repository',{'full_name':'other/repo'}),
                            ('repository',[])]:
            with self.subTest(field=field,value=value):
                row=self.row();row[field]=value
                with self.assertRaises(ValueError):self.client(lambda *args:row).attempt(42,2,self.commit,**self.binding)
        self.assertTrue(all(method=='GET' for method,_,_ in self.calls))

    def test_invalid_bindings_and_foreign_get_are_rejected_before_transport(self):
        client=self.client(lambda *args:self.fail('unexpected transport'))
        for run,attempt,commit in [(True,2,self.commit),(42,0,self.commit),(42,2,'bad')]:
            with self.subTest(run=run,attempt=attempt),self.assertRaises(ValueError):
                client.attempt(run,attempt,commit,**self.binding)
        with self.assertRaises(ValueError):client.attempt(42,2,self.commit,expected_ref='alpha',expected_workflow='../release.yml')
        with self.assertRaises(ValueError):client.get('/repos/other/repo/actions/runs/42')
        self.assertEqual(self.calls,[])

    def test_terminal_failure_is_typed_and_retains_exact_attempt(self):
        from build_manager.github import GitHubWorkflowFailed
        with self.assertRaises(GitHubWorkflowFailed) as caught:
            self.client(lambda *args:self.row(status='completed',conclusion='failure')).wait_attempt(
                42,2,self.commit,**self.binding)
        self.assertEqual(caught.exception.result['run_attempt'],2)

    def test_http500_rerun_is_reconciled_once_despite_stale_cancelled_parent_status(self):
        from urllib.error import HTTPError
        posted=[False]
        def action(method,path,body):
            if method=='POST':
                posted[0]=True
                raise HTTPError('https://private.invalid/?token=hidden',500,'private',{},None)
            if path.endswith('/attempts/2'):return self.row()
            return self.row(attempt=2 if posted[0] else 1,status='completed',conclusion='cancelled')
        value=self.client(action).rerun_failed(42,self.commit,expected_attempt=1,**self.binding,
            confirmed=True,timeout=3,poll=1,cancelled=self.clock)
        self.assertEqual(value['status'],'accepted')
        self.assertTrue(value['post_response_unknown'])
        self.assertEqual(value['observation']['status'],'queued')
        self.assertEqual(sum(m=='POST' for m,_,_ in self.calls),1)

    def test_ambiguous_write_stays_unknown_until_later_get_only_reconciliation(self):
        from urllib.error import URLError
        from build_manager.github import GitHubOutcomeUnknown
        advanced=[False]
        def action(method,path,body):
            if method=='POST':raise URLError('private detail')
            if path.endswith('/attempts/2'):return self.row()
            return self.row(attempt=2 if advanced[0] else 1,status='completed',conclusion='failure')
        client=self.client(action)
        with self.assertRaises(GitHubOutcomeUnknown) as caught:
            client.rerun_failed(42,self.commit,expected_attempt=1,**self.binding,
                confirmed=True,timeout=2,poll=1,cancelled=self.clock)
        self.assertEqual(caught.exception.run_attempt,2)
        advanced[0]=True
        self.assertEqual(client.reconcile_rerun(42,self.commit,expected_attempt=1,**self.binding)['status'],'accepted')
        self.assertEqual(sum(m=='POST' for m,_,_ in self.calls),1)

    def test_unauthorized_or_changed_attempt_never_reruns(self):
        client=self.client(lambda *args:self.row(attempt=3,status='completed',conclusion='failure'))
        with self.assertRaises(ValueError):client.rerun_failed(42,self.commit,expected_attempt=1,**self.binding)
        self.assertEqual(self.calls,[])
        with self.assertRaises(ValueError):client.rerun_failed(42,self.commit,expected_attempt=1,**self.binding,confirmed=True)
        self.assertFalse(any(m=='POST' for m,_,_ in self.calls))

    def test_transient_gets_retry_but_not_auth_failures_or_post(self):
        from urllib.error import HTTPError
        from build_manager.github import GitHubHTTPError
        sequence=iter([503,429,None])
        def action(*args):
            code=next(sequence)
            if code:raise HTTPError('https://private.invalid',code,'private',{},None)
            return {'ok':True}
        client=self.client(action)
        self.assertEqual(client.get(client.base+'/actions/runs/42',cancelled=self.clock),{'ok':True})
        self.assertEqual(len(self.calls),3)
        self.calls.clear()
        client=self.client(lambda *args:(_ for _ in ()).throw(HTTPError('https://private.invalid',401,'private',{},None)))
        with self.assertRaises(GitHubHTTPError) as caught:client.get(client.base+'/actions/runs/42')
        self.assertEqual(caught.exception.status,401);self.assertEqual(len(self.calls),1)
        self.assertNotIn('private',str(caught.exception))

    def test_get_deadline_and_cancel_are_bounded_without_mutation(self):
        from build_manager.github import GitHubUnavailable
        client=self.client(lambda *args:(_ for _ in ()).throw(GitHubUnavailable('unavailable')))
        with self.assertRaises(TimeoutError):
            client.get(client.base+'/actions/runs/42',timeout=.6,poll=.5,max_attempts=5,cancelled=self.clock)
        self.assertEqual(self.clock.now,.6)
        cancelled=Event();cancelled.set();before=len(self.calls)
        self.assertEqual(client.wait_attempt(42,2,self.commit,**self.binding,cancelled=cancelled)['status'],'cancelled')
        self.assertEqual(len(self.calls),before)

    def test_invalid_budget_and_preexisting_cancel_never_reach_transport(self):
        client=self.client(lambda *args:self.fail('unexpected transport'))
        for options in ({'timeout':0},{'timeout':float('nan')},{'poll':0},{'poll':float('inf')}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                client.rerun_failed(42,self.commit,expected_attempt=1,**self.binding,confirmed=True,**options)
        cancelled=Event();cancelled.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled before'):
            client.rerun_failed(42,self.commit,expected_attempt=1,**self.binding,confirmed=True,cancelled=cancelled)
        self.assertEqual(self.calls,[])

    def test_cancel_during_preflight_get_prevents_post(self):
        cancelled=Event()
        def action(*args):
            cancelled.set()
            return self.row(attempt=1,status='completed',conclusion='failure')
        with self.assertRaisesRegex(RuntimeError,'cancelled before'):
            self.client(action).rerun_failed(42,self.commit,expected_attempt=1,**self.binding,confirmed=True,cancelled=cancelled)
        self.assertEqual([m for m,_,_ in self.calls],['GET'])

    def test_cancel_after_post_preserves_unknown_and_never_replays(self):
        from build_manager.github import GitHubOutcomeUnknown
        cancelled=Event()
        def action(method,path,body):
            if method=='POST':cancelled.set();return {}
            return self.row(attempt=1,status='completed',conclusion='failure')
        with self.assertRaises(GitHubOutcomeUnknown):
            self.client(action).rerun_failed(42,self.commit,expected_attempt=1,**self.binding,confirmed=True,cancelled=cancelled)
        self.assertEqual([m for m,_,_ in self.calls],['GET','POST'])

    def test_non_json_get_retries_are_read_only_and_bounded(self):
        from build_manager.github import GitHubProtocolError
        replies=iter([GitHubProtocolError('unusable JSON'),{'ok':True}])
        def action(*args):
            value=next(replies)
            if isinstance(value,Exception):raise value
            return value
        client=self.client(action)
        self.assertEqual(client.get(client.base+'/actions/runs/42',cancelled=self.clock),{'ok':True})
        self.assertEqual([m for m,_,_ in self.calls],['GET','GET'])

    def test_post_intent_unreadable_or_timed_out_observation_is_typed_unknown(self):
        from build_manager.github import GitHubOutcomeUnknown, GitHubProtocolError
        for failure in (GitHubProtocolError('bad JSON'),TimeoutError('read deadline')):
            posted=[False];self.calls.clear();self.clock.now=0
            def action(method,path,body):
                if method=='POST':posted[0]=True;return {}
                if posted[0]:raise failure
                return self.row(attempt=1,status='completed',conclusion='failure')
            with self.subTest(error=type(failure).__name__),self.assertRaises(GitHubOutcomeUnknown):
                self.client(action).rerun_failed(42,self.commit,expected_attempt=1,**self.binding,
                    confirmed=True,timeout=1,poll=.5,cancelled=self.clock)
            self.assertEqual(sum(m=='POST' for m,_,_ in self.calls),1)

    def test_cancel_during_reconciliation_get_stays_unknown_after_post(self):
        from build_manager.github import GitHubOutcomeUnknown, GitHubUnavailable
        cancelled=Event();posted=[False]
        def action(method,path,body):
            if method=='POST':posted[0]=True;return {}
            if posted[0]:cancelled.set();raise GitHubUnavailable('read failed')
            return self.row(attempt=1,status='completed',conclusion='failure')
        with self.assertRaises(GitHubOutcomeUnknown):
            self.client(action).rerun_failed(42,self.commit,expected_attempt=1,**self.binding,
                confirmed=True,cancelled=cancelled)
        self.assertEqual(sum(m=='POST' for m,_,_ in self.calls),1)


class GitHubJobLogTests(unittest.TestCase):
    def response(self, content):
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=content;response.read1.side_effect=[content,b'']
        response.headers.get.return_value='';response.isclosed.return_value=False
        return response

    def redirected(self, location):
        from urllib.error import HTTPError
        from unittest.mock import Mock
        client=GitHub('fixture/repo','synthetic-token')
        client.opener=Mock();client.opener.open.side_effect=HTTPError('https://api.github.com',302,'redirect',{'Location':location},None)
        return client

    def test_signed_storage_receives_no_authorization_and_has_byte_bound(self):
        from unittest.mock import Mock,patch
        client=self.redirected('https://provider.blob.core.windows.net/log?sig=private')
        opener=Mock();response=self.response(b'bounded log');opener.open.return_value=response
        with patch('build_manager.github.build_opener',return_value=opener):
            self.assertEqual(client.job_log(52,max_bytes=20),'bounded log')
        self.assertEqual(client.opener.open.call_args.args[0].get_header('Authorization'),'Bearer synthetic-token')
        self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
        self.assertEqual(response.read1.call_args_list[0].args,(21,))
        response.read.assert_not_called()

    def test_untrusted_nonhttps_credentials_fragment_and_redirect_chain_are_refused(self):
        from urllib.error import HTTPError
        from unittest.mock import Mock,patch
        from build_manager.github import GitHubHTTPError
        for location in ('http://provider.blob.core.windows.net/x','https://evil.invalid/x',
                         'https://provider.blob.core.windows.net.evil.invalid/x',
                         'https://user:secret@provider.blob.core.windows.net/x',
                         'https://provider.blob.core.windows.net/x#secret',
                         'https://provider.blob.core.windows.net:private-secret/x',
                         'https://provider.blob.core.windows.net/x?secret=\nvalue'):
            client=self.redirected(location)
            with self.subTest(location=location),patch('build_manager.github.build_opener') as anonymous:
                with self.assertRaises(ValueError):client.job_log(52)
                anonymous.assert_not_called()
        client=self.redirected('https://provider.blob.core.windows.net/x')
        opener=Mock();opener.open.side_effect=HTTPError('private',302,'redirect',{'Location':'https://evil.invalid'},None)
        with patch('build_manager.github.build_opener',return_value=opener),self.assertRaises(GitHubHTTPError) as caught:
            client.job_log(52)
        self.assertEqual(caught.exception.status,302)
        self.assertNotIn('private',str(caught.exception))

    def test_oversized_log_and_exhausted_redirect_budget_are_rejected(self):
        from unittest.mock import Mock,patch
        from build_manager.github import GitHubUnavailable
        client=GitHub('fixture/repo');client.opener=Mock();client.opener.open.return_value=self.response(b'x'*11)
        with self.assertRaisesRegex(ValueError,'byte bound'):client.job_log(52,max_bytes=10)
        client=self.redirected('https://provider.blob.core.windows.net/x')
        ticks=iter([0,31]);client.clock=lambda:next(ticks)
        with patch('build_manager.github.build_opener') as anonymous,self.assertRaises(GitHubUnavailable):client.job_log(52,timeout=30)
        anonymous.assert_not_called()

    def test_non_json_error_is_typed_and_does_not_expose_payload(self):
        from unittest.mock import Mock
        from build_manager.github import GitHubProtocolError
        client=GitHub('fixture/repo');client.opener=Mock();client.opener.open.return_value=self.response(b'<!DOCTYPE html>private-token')
        with self.assertRaises(GitHubProtocolError) as caught:client.request('GET',client.base+'/actions/runs/42')
        self.assertNotIn('private-token',str(caught.exception))


    def test_trickling_log_cannot_extend_total_deadline(self):
        from unittest.mock import Mock
        from build_manager.github import GitHubUnavailable
        clock=Clock();response=self.response(b'')
        def trickle(size):
            clock.now+=.4
            return b'x'
        response.read1.side_effect=trickle
        client=GitHub('fixture/repo',clock=clock.read);client.opener=Mock();client.opener.open.return_value=response
        with self.assertRaises(GitHubUnavailable):client.job_log(52,timeout=1)
        self.assertEqual(response.read1.call_count,3)
        self.assertAlmostEqual(response.fp.raw._sock.settimeout.call_args_list[-1].args[0],.2)
        self.assertLess(clock.now,1.5)
