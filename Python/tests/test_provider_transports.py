"""Injected provider responses and a harmless CLI; no credentials or real upload."""
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from build_manager.app_store_connect import API, AppStoreConnectClient, LookupUnavailable, NoRedirect, SigningDependencyError, token, wait_for_processed_build
from build_manager.firebase import FirebaseCLI, FirebaseError
from build_manager.providers import ProviderOutcomeUnknown


class AppStoreTransportTests(unittest.TestCase):
    def client(self):
        signer = Mock(return_value='synthetic-bearer-token')
        client = AppStoreConnectClient({'key_path': 'unused fixture'}, token_factory=signer)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        client.opener = Mock()
        client.opener.open.return_value = response
        return client, response, signer

    def test_same_origin_pagination_signs_each_request_and_preserves_items(self):
        client, response, signer = self.client()
        response.read.side_effect = [json.dumps({'data': [{'id': 'one'}], 'links': {'next': API + '/v1/builds?page=2'}}).encode(),
                                     b'{"data":[{"id":"two"}]}']
        self.assertEqual(client.list('/v1/builds', limit=200), [{'id': 'one'}, {'id': 'two'}])
        self.assertEqual(signer.call_count, 3)
        requests = client.opener.open.call_args_list
        self.assertEqual(requests[0].args[0].full_url, API + '/v1/builds?limit=200')
        self.assertEqual(requests[1].args[0].get_header('Authorization'), 'Bearer synthetic-bearer-token')
        self.assertEqual(requests[1].kwargs['timeout'], 30)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://foreign.invalid'))

    def test_foreign_pagination_is_rejected_before_signing_or_opening_it(self):
        client, response, signer = self.client()
        response.read.return_value = b'{"data":[],"links":{"next":"https://foreign.invalid/v1/builds"}}'
        with self.assertRaises(ValueError):
            client.list('/v1/builds')
        self.assertEqual(client.opener.open.call_count, 1)
        self.assertEqual(signer.call_count, 2)
        for path in ('https://api.appstoreconnect.apple.com@foreign.invalid/v1/builds',
                     'http://api.appstoreconnect.apple.com/v1/builds', '//foreign.invalid/v1/builds'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.request('GET', path)
        self.assertEqual(signer.call_count, 2)

    def test_pagination_cycles_fail_and_error_details_redact_the_bearer(self):
        client, response, _ = self.client()
        response.read.return_value = json.dumps({'data': [], 'links': {'next': API + '/v1/builds?page=2'}}).encode()
        with self.assertRaisesRegex(RuntimeError, 'repeated'):
            client.list('/v1/builds')
        self.assertEqual(client.opener.open.call_count, 2)
        body = json.dumps({'errors': [{'detail': 'rejected synthetic-bearer-token'}]}).encode()
        client.opener.open.side_effect = HTTPError(API + '/v1/builds', 401, '', {}, io.BytesIO(body))
        with self.assertRaises(RuntimeError) as failure:
            client.request('GET', '/v1/builds')
        self.assertNotIn('synthetic-bearer-token', str(failure.exception))
        self.assertIn('[redacted]', str(failure.exception))

    def test_lost_write_and_read_are_not_retried(self):
        for method in ('POST', 'PATCH', 'GET'):
            client, _, _ = self.client()
            client.opener.open.side_effect = URLError('lost session')
            expected = RuntimeError if method == 'GET' else ProviderOutcomeUnknown
            with self.subTest(method=method), self.assertRaises(expected):
                client.request(method, '/v1/betaGroups', body={} if method != 'GET' else None)
            self.assertEqual(client.opener.open.call_count, 1)

    def test_processing_lookup_outage_recovers_without_reupload_or_deadline_reset(self):
        client = Mock()
        ready = {'id': 'build', 'attributes': {'processingState': 'VALID'}}
        client.list.side_effect = [LookupUnavailable('offline'), [ready]]
        sleep = Mock()
        self.assertEqual(wait_for_processed_build(client, app_id='app', number='41', version='2.0',
            platform='IOS', timeout=10, interval=30, sleep=sleep, clock=Mock(side_effect=[0, 7])), ready)
        sleep.assert_called_once_with(3)
        self.assertEqual(client.list.call_count, 2)
        self.assertEqual(client.list.call_args_list[0], client.list.call_args_list[1])
        client.request.assert_not_called()

    def test_processing_lookup_outage_exhausts_original_deadline_and_other_errors_stop(self):
        client = Mock()
        client.list.side_effect = LookupUnavailable('offline')
        sleep = Mock()
        with self.assertRaises(LookupUnavailable):
            wait_for_processed_build(client, app_id='app', number='41', version='2.0', platform='IOS',
                timeout=10, interval=6, sleep=sleep, clock=Mock(side_effect=[0, 4, 10]))
        sleep.assert_called_once_with(6)
        client.list.side_effect = RuntimeError('HTTP 401')
        with self.assertRaisesRegex(RuntimeError, '401'):
            wait_for_processed_build(client, app_id='app', number='41', version='2.0', platform='IOS',
                timeout=10, interval=6, sleep=sleep)
        self.assertEqual(sleep.call_count, 1)

    def test_only_transient_read_responses_are_poll_retryable(self):
        for method, code, retryable in [('GET', 503, True), ('GET', 429, True), ('GET', 401, False),
                                        ('POST', 503, False), ('PATCH', 429, False)]:
            client, _, _ = self.client()
            client.opener.open.side_effect = HTTPError(API + '/v1/builds', code, '', {}, io.BytesIO(b'{}'))
            with self.subTest(method=method, code=code), self.assertRaises(RuntimeError) as failure:
                client.request(method, '/v1/builds')
            self.assertEqual(isinstance(failure.exception, LookupUnavailable), retryable)
            self.assertEqual(client.opener.open.call_count, 1)

    def test_processing_wait_is_exact_bounded_and_calls_project_validation(self):
        client = Mock()
        processing = {'id': 'build', 'attributes': {'processingState': 'PROCESSING'}}
        ready = {'id': 'build', 'attributes': {'processingState': 'VALID'}}
        client.list.side_effect = [[], [processing], [ready]]
        validate, sleep, progress = Mock(), Mock(), Mock()
        result = wait_for_processed_build(client, app_id='other-app', number='41', version='2.0', platform='MAC_OS',
            timeout=60, interval=30, validate=validate, progress=progress, sleep=sleep, clock=Mock(side_effect=[0, 0, 45]))
        self.assertEqual(result, ready)
        self.assertEqual(client.list.call_args.kwargs['filter[preReleaseVersion.platform]'], 'MAC_OS')
        self.assertEqual(client.list.call_args.kwargs['filter[app]'], 'other-app')
        self.assertEqual(client.list.call_args.kwargs['filter[version]'], '41')
        self.assertEqual(client.list.call_args.kwargs['filter[preReleaseVersion.version]'], '2.0')
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 15])
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(progress.call_count, 2)
        client.list.side_effect = None; client.list.return_value = []
        with self.assertRaisesRegex(RuntimeError, 'do not re-upload'):
            wait_for_processed_build(client, app_id='other', number='1', version='1', platform='IOS', timeout=1,
                interval=1, clock=Mock(side_effect=[0, 2]), sleep=sleep)

    def test_optional_signing_dependency_is_only_needed_when_signing(self):
        with patch.dict(sys.modules, {'cryptography': None}):
            with self.assertRaises(SigningDependencyError):
                token({'key_path': 'never-read'})
        code = ('import sys; import build_manager.app_store_connect,build_manager.firebase; '
                'assert not any(n.startswith(("PySide6", "mobile_build", "Scripts", "cryptography")) for n in sys.modules)')
        subprocess.run([sys.executable, '-c', code], check=True)


class FirebaseTransportTests(unittest.TestCase):
    def test_reads_login_and_direct_upload_keep_explicit_caller_arguments(self):
        client = FirebaseCLI('/fixture/firebase', '/private/workspace')
        response = subprocess.CompletedProcess([], 0, '{"result":[{"projectId":"second-project"}]}')
        with patch('build_manager.firebase.subprocess.run', return_value=response) as run:
            self.assertEqual(client.query('projects:list'), [{'projectId': 'second-project'}])
            self.assertEqual(run.call_args.args[0], ['/fixture/firebase', 'projects:list', '--json', '--non-interactive'])
            self.assertEqual(run.call_args.kwargs['cwd'], Path('/private/workspace'))
            client.login(reauth=True)
            self.assertEqual(run.call_args.args[0], ['/fixture/firebase', 'login', '--reauth'])
            client.distribute('a path/app.apk', app_id='other-app', group='other-group', release_notes='notes path.txt')
            self.assertEqual(run.call_args.args[0], ['/fixture/firebase', 'appdistribution:distribute', 'a path/app.apk',
                '--app', 'other-app', '--groups', 'other-group', '--release-notes-file', 'notes path.txt', '--non-interactive'])
            self.assertNotIn('capture_output', run.call_args.kwargs)

    def test_receipt_reads_do_not_replay_a_failed_or_ambiguous_upload(self):
        client = FirebaseCLI('firebase', '/private/workspace')
        for code, output in [(1, 'token=private diagnostic'), (0, 'not json'), (0, '{"result":{}}'),
                             (0, '{"status":"error","result":{"release":"ambiguous"}}')]:
            with self.subTest(code=code, output=output), patch('build_manager.firebase.subprocess.run',
                    return_value=subprocess.CompletedProcess([], code, output)) as run:
                with self.assertRaises(ProviderOutcomeUnknown) as failure:
                    client.distribute('app.apk', app_id='other', group='testers', release_notes='notes.txt', capture_result=True)
                self.assertEqual(run.call_count, 1)
                self.assertNotIn('private diagnostic', str(failure.exception))
                self.assertNotIn('not json', str(failure.exception))
        with patch('build_manager.firebase.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '{"result":{"release":"id"}}')):
            self.assertEqual(client.distribute('app.apk', app_id='other', group='testers', release_notes='notes.txt',
                capture_result=True), {'release': 'id'})

    def test_query_failure_does_not_echo_private_output_or_sign_in(self):
        client = FirebaseCLI('firebase', '/private/workspace')
        for output in ('private token', '{"status":"error","result":{}}'):
            with patch('build_manager.firebase.subprocess.run', return_value=subprocess.CompletedProcess([], 1, output)) as run:
                with self.assertRaises(FirebaseError) as failure:
                    client.query('login:list')
                self.assertNotIn(output, str(failure.exception))
                self.assertEqual(run.call_count, 1)

    def test_distribution_void_success_is_a_command_receipt_not_an_unknown_upload(self):
        client = FirebaseCLI('firebase', '/private/workspace')
        for output in ('{"status":"success"}', '{"status":"success","result":null}'):
            with self.subTest(output=output), patch('build_manager.firebase.subprocess.run',
                    return_value=subprocess.CompletedProcess([], 0, output)) as run:
                self.assertEqual(client.distribute('app.apk', app_id='other', group='friends',
                    release_notes='notes.txt', capture_result=True),
                    dict(cli_status='success', receipt_kind='completed-command'))
                self.assertEqual(run.call_count, 1)
        for code, output in [(1, '{"status":"success"}'), (0, '{}'),
                             (0, '{"status":"success","result":{}}')]:
            with self.subTest(code=code, output=output), patch('build_manager.firebase.subprocess.run',
                    return_value=subprocess.CompletedProcess([], code, output)):
                with self.assertRaises(ProviderOutcomeUnknown):
                    client.distribute('app.apk', app_id='other', group='friends',
                                      release_notes='notes.txt', capture_result=True)
        with patch('build_manager.firebase.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0, '{"status":"success"}')):
            with self.assertRaises(FirebaseError): client.query('projects:list')

    def test_real_harmless_cli_receives_one_literal_distribution_and_receipt(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            # Use Python as the executable and its -c option as a harmless argv prefix.
            script = root / 'cli.py'
            record = root / 'calls.json'
            script.write_text('import json,sys\nfrom pathlib import Path\n'
                f'p=Path({str(record)!r}); p.write_text(json.dumps(sys.argv[1:]))\n'
                'print(json.dumps({"result":{"release":"fixture"}}))\n')
            client = FirebaseCLI(sys.executable, root)
            original = client.distribution_command
            def command(*args, **kwargs):
                return [sys.executable, str(script), *original(*args, **kwargs)[1:]]
            with patch.object(client, 'distribution_command', side_effect=command):
                self.assertEqual(client.distribute('literal ; $(nothing).apk', app_id='other-app', group='testers',
                    release_notes='notes.txt', capture_result=True), {'release': 'fixture'})
            self.assertEqual(json.loads(record.read_text())[1], 'literal ; $(nothing).apk')
