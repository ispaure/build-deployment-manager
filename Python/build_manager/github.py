"""Explicit GitHub repository transport; project adapters supply workflows/policy."""
import json
import re
from threading import Event
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self, repository, token=None, *, transport=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Use an explicit owner/repository name.')
        self.repository, self.token, self.transport = repository, token, transport
        self.base = '/repos/' + repository
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None):
        if not path.startswith(self.base + '/') and path != self.base:
            raise ValueError('Request is outside the configured repository.')
        if self.transport is not None:
            return self.transport(method, path, body)
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if method != 'GET' and not self.token:
            raise ValueError('GitHub write operations need a configured credential reference.')
        request = Request('https://api.github.com' + path, method=method,
            headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except HTTPError as error:
            # Do not dump provider payloads, headers or a token-bearing request.
            raise RuntimeError(f'GitHub HTTP {error.code}; inspect repository/workflow access.') from None
        except URLError:
            raise RuntimeError('GitHub is unreachable. Do not repeat an accepted dispatch blindly.') from None

    def verify(self):
        return self.request('GET', self.base)

    def resolve_ref(self, ref):
        for family in ('heads', 'tags'):
            try:
                row = self.request('GET', self.base + '/git/ref/' + family + '/' + quote(ref, safe=''))
            except RuntimeError as error:
                if 'HTTP 404' in str(error):
                    continue
                raise
            obj = row['object']
            if obj['type'] == 'tag':
                obj = self.request('GET', self.base + '/git/tags/' + obj['sha'])['object']
            if obj['type'] != 'commit':
                raise ValueError('Selected ref does not identify a commit.')
            return obj['sha']
        raise ValueError('The selected branch/tag has not been published.')

    def dispatch(self, workflow, ref, expected_commit, inputs=None, *, confirmed=False):
        if not confirmed:
            raise ValueError('Review and confirm a hosted operation before dispatch.')
        if self.resolve_ref(ref) != expected_commit:
            raise ValueError('The published ref differs from the reviewed source; no run was dispatched.')
        result = self.request('POST', self.base + '/actions/workflows/' + quote(workflow, safe='') + '/dispatches',
                              {'ref': ref, 'inputs': inputs or {}})
        run_id = result.get('workflow_run_id')
        if not isinstance(run_id, int) or run_id <= 0:
            raise RuntimeError('Dispatch accepted without a run identity. Inspect GitHub; do not dispatch again automatically.')
        return run_id

    def wait(self, run_id, expected_commit, *, timeout=10800, poll=15, cancelled=None, progress=None):
        cancelled = cancelled if cancelled is not None else Event()
        progress = progress or (lambda value: None)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancelled.is_set():
                self.request('POST', self.base + f'/actions/runs/{run_id}/cancel')
                return dict(status='cancelled', run_id=run_id)
            result = self.request('GET', self.base + f'/actions/runs/{run_id}')
            if result.get('head_sha') != expected_commit:
                raise ValueError('Hosted result belongs to different source.')
            progress(dict(run_id=run_id, status=result['status'], conclusion=result.get('conclusion')))
            if result['status'] == 'completed':
                if result['conclusion'] != 'success':
                    raise RuntimeError('Hosted validation did not pass: ' + str(result['conclusion']))
                return result
            cancelled.wait(poll)
        # Preserve a known live run rather than launching a duplicate or claiming
        # that dispatch success is test success.
        raise TimeoutError(f'Hosted run {run_id} exceeded the observation budget; inspect/resume that exact run.')
