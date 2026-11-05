"""Explicit GitHub repository transport; project adapters supply workflows/policy."""
import json
from math import isfinite
import re
from threading import Event
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .providers import ProviderOutcomeUnknown


class GitHubHTTPError(RuntimeError):
    """Safe provider status; response bodies and credential-bearing requests stay private."""
    def __init__(self, status, method='GET'):
        self.status, self.method = status, method
        super().__init__(f'GitHub HTTP {status}; inspect repository/workflow access.')


class GitHubInspectionCancelled(RuntimeError):
    """A read-only observation was stopped; no provider write is implied."""


class GitHubUnavailable(RuntimeError):
    """A transport failure never proves that a write was rejected."""


class GitHubProtocolError(RuntimeError):
    """An unusable provider response, without its potentially private payload."""


class GitHubOutcomeUnknown(ProviderOutcomeUnknown):
    def __init__(self, run_id, run_attempt):
        self.run_id, self.run_attempt = run_id, run_attempt
        super().__init__(f'GitHub rerun outcome is unknown for run {run_id}, attempt {run_attempt}; '
                         'reconcile this exact attempt before any further write.')


class GitHubWorkflowFailed(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__('Hosted validation did not pass: ' + str(result.get('conclusion')))


def positive(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(name + ' must be finite and positive.')


def transient(error):
    return (isinstance(error, (GitHubUnavailable, GitHubProtocolError)) or isinstance(error, GitHubHTTPError)
            and error.status in {429, 500, 502, 503, 504})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self, repository, token=None, *, transport=None, clock=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Use an explicit owner/repository name.')
        self.repository, self.token, self.transport = repository, token, transport
        self.clock = clock or time.monotonic
        self.base = '/repos/' + repository
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, *, timeout=30):
        if not path.startswith(self.base + '/') and path != self.base:
            raise ValueError('Request is outside the configured repository.')
        positive(timeout, 'HTTP timeout')
        try:
            if self.transport is not None:
                return self.transport(method, path, body)
            headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}
            if self.token:
                headers['Authorization'] = 'Bearer ' + self.token
            if method != 'GET' and not self.token:
                raise ValueError('GitHub write operations need a configured credential reference.')
            request = Request('https://api.github.com' + path, method=method,
                headers=headers, data=json.dumps(body).encode() if body is not None else None)
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except HTTPError as error:
            raise GitHubHTTPError(error.code, method) from None
        except (URLError, OSError, TimeoutError):
            raise GitHubUnavailable('GitHub is unreachable. Do not repeat an accepted dispatch blindly.') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GitHubProtocolError('GitHub returned unusable JSON; inspect the recorded operation without repeating its write.') from None

    def get(self, path, *, timeout=30, max_attempts=3, poll=.25, cancelled=None):
        """Retry only transient reads within one deadline; never replay a write."""
        positive(timeout, 'GET timeout')
        positive(poll, 'GET interval')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError('GET attempts must be between one and five.')
        cancelled = cancelled or Event()
        deadline = self.clock() + timeout
        for attempt in range(max_attempts):
            if cancelled.is_set():
                raise GitHubInspectionCancelled('GitHub inspection cancelled.')
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError('GitHub inspection exceeded its read budget.')
            try:
                result = self.request('GET', path, timeout=min(30, remaining))
                if self.clock() > deadline:
                    raise TimeoutError('GitHub inspection exceeded its read budget.')
                return result
            except (GitHubHTTPError, GitHubUnavailable, GitHubProtocolError) as error:
                if not transient(error) or attempt + 1 == max_attempts:
                    raise
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError('GitHub inspection exceeded its read budget.') from None
                cancelled.wait(min(poll, remaining))

    def job_log(self, job_id, *, max_bytes=1024*1024, timeout=30):
        """One bounded GET of a job log, never forwarding auth to signed storage.

        Returned text remains private provider evidence; callers own redaction,
        classification and retention. This does not classify or rerun any job.
        """
        if type(job_id) is not int or job_id <= 0 or type(max_bytes) is not int or not 0 < max_bytes <= 4*1024*1024:
            raise ValueError('Select one job and a log bound no larger than four MiB.')
        positive(timeout, 'Job log timeout')
        deadline = self.clock()+timeout
        headers = {'Accept':'application/vnd.github+json'}
        if self.token:
            headers['Authorization'] = 'Bearer '+self.token
        request = Request('https://api.github.com'+self.base+f'/actions/jobs/{job_id}/logs', headers=headers)
        try:
            try:
                response = self.opener.open(request, timeout=min(30,timeout))
            except HTTPError as error:
                if error.code != 302:
                    raise
                location = error.headers.get('Location','')
                if not isinstance(location,str) or not location.isascii() or any(ord(c)<=32 or ord(c)==127 for c in location):
                    raise ValueError('Job log redirect is outside approved provider storage.') from None
                try:
                    target = urlsplit(location)
                    port = target.port
                except ValueError:
                    raise ValueError('Job log redirect is outside approved provider storage.') from None
                host = target.hostname or ''
                allowed = any(host.endswith('.'+domain) for domain in ('actions.githubusercontent.com','blob.core.windows.net'))
                if (target.scheme != 'https' or not allowed or target.username or target.password
                        or port not in (None,443) or target.fragment):
                    raise ValueError('Job log redirect is outside approved provider storage.') from None
                remaining = deadline-self.clock()
                if remaining <= 0:
                    raise TimeoutError('Job log exceeded its read budget.')
                # A fresh opener/request carries no API bearer to signed storage.
                response = build_opener(NoRedirect()).open(Request(target.geturl()), timeout=min(30,remaining))
            with response:
                # Blob log responses use fixed/EOF framing. read1 performs one
                # underlying read, unlike read(n) which can fill forever on a
                # trickling connection. Cap every owned socket read by time left.
                if response.headers.get('Transfer-Encoding','').lower() == 'chunked':
                    raise ValueError('Job log uses unsupported transfer framing.')
                reader = getattr(response,'read1',None)
                socket = getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
                if not callable(reader) or not callable(getattr(socket,'settimeout',None)):
                    raise ValueError('Job log lacks a deadline-aware stream.')
                chunks, size = [], 0
                while not response.isclosed():
                    remaining = deadline-self.clock()
                    if remaining <= 0:
                        raise TimeoutError('Job log exceeded its read budget.')
                    socket.settimeout(min(30,remaining))
                    chunk = reader(min(65536,max_bytes+1-size))
                    if not chunk:
                        break
                    chunks.append(chunk); size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Job log exceeds the selected byte bound.')
                content = b''.join(chunks)
            if self.clock()>deadline:
                raise TimeoutError('Job log exceeded its read budget.')
            return content.decode('utf-8',errors='replace')
        except HTTPError as error:
            raise GitHubHTTPError(error.code,'GET') from None
        except (URLError,OSError,TimeoutError):
            raise GitHubUnavailable('GitHub job log could not be read within its bounded request.') from None

    def _binding(self, run_id, attempt, commit, ref, workflow):
        if (type(run_id) is not int or run_id <= 0 or type(attempt) is not int or attempt <= 0
                or not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit)
                or not isinstance(ref, str) or not ref or not isinstance(workflow, str)):
            raise ValueError('Select an exact run, attempt, commit, ref and workflow.')
        ref = re.sub(r'^refs/(heads|tags)/', '', ref)
        if not ref or not re.fullmatch(r'(?:\.github/workflows/)?[A-Za-z0-9_.-]+\.ya?ml', workflow):
            raise ValueError('Select an exact ref and workflow path.')
        workflow = workflow if workflow.startswith('.github/workflows/') else '.github/workflows/' + workflow
        return ref, workflow

    def _verify_run(self, result, run_id, attempt, commit, ref, workflow):
        ref, workflow = self._binding(run_id, attempt, commit, ref, workflow)
        if (not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] != run_id
                or type(result.get('run_attempt')) is not int or result['run_attempt'] != attempt
                or result.get('head_sha') != commit or result.get('head_branch') != ref
                or not isinstance(result.get('path'), str) or result['path'].split('@')[0] != workflow
                or not isinstance(result.get('repository'), dict)
                or result['repository'].get('full_name') != self.repository):
            raise ValueError('Hosted attempt differs from the reviewed run/source/ref/workflow.')
        return result

    def attempt(self, run_id, attempt, expected_commit, *, expected_ref, expected_workflow, timeout=30, cancelled=None):
        self._binding(run_id, attempt, expected_commit, expected_ref, expected_workflow)
        result = self.get(self.base + f'/actions/runs/{run_id}/attempts/{attempt}', timeout=timeout, cancelled=cancelled)
        return self._verify_run(result, run_id, attempt, expected_commit, expected_ref, expected_workflow)

    def wait_attempt(self, run_id, attempt, expected_commit, *, expected_ref, expected_workflow,
                     timeout=10800, poll=15, cancelled=None, progress=None):
        """Observe exactly this attempt; stopping observation sends no provider write.

        A queued aggregate never becomes success merely because visible jobs ended.
        Projects may separately verify their fixed workflow's terminal witness.
        """
        self._binding(run_id, attempt, expected_commit, expected_ref, expected_workflow)
        positive(timeout, 'Observation timeout'); positive(poll, 'Observation interval')
        cancelled, progress = cancelled or Event(), progress or (lambda value: None)
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if cancelled.is_set():
                return dict(status='cancelled', run_id=run_id, run_attempt=attempt)
            remaining = deadline-self.clock()
            if remaining <= 0:
                break
            try:
                result = self.attempt(run_id, attempt, expected_commit, expected_ref=expected_ref,
                    expected_workflow=expected_workflow, timeout=remaining, cancelled=cancelled)
            except GitHubInspectionCancelled:
                return dict(status='cancelled', run_id=run_id, run_attempt=attempt)
            progress(dict(run_id=run_id, run_attempt=attempt, status=result['status'], conclusion=result.get('conclusion')))
            if result['status'] == 'completed':
                if result.get('conclusion') != 'success':
                    raise GitHubWorkflowFailed(result)
                return result
            cancelled.wait(min(poll, max(0, deadline-self.clock())))
        raise TimeoutError(f'Hosted run {run_id}, attempt {attempt} exceeded observation; resume this exact attempt.')

    def reconcile_rerun(self, run_id, expected_commit, *, expected_attempt, expected_ref,
                        expected_workflow, timeout=60, poll=1, cancelled=None):
        """GET-only reconciliation of a recorded intent to create attempt N+1."""
        self._binding(run_id, expected_attempt, expected_commit, expected_ref, expected_workflow)
        positive(timeout, 'Reconciliation timeout'); positive(poll, 'Reconciliation interval')
        cancelled = cancelled or Event(); deadline = self.clock()+timeout
        target = expected_attempt + 1
        while self.clock() < deadline and not cancelled.is_set():
            try:
                remaining = deadline-self.clock()
                if remaining <= 0:
                    break
                current = self.get(self.base + f'/actions/runs/{run_id}', timeout=remaining, cancelled=cancelled)
                number = current.get('run_attempt') if isinstance(current, dict) else None
                if number not in (expected_attempt, target) or type(number) is not int:
                    raise GitHubOutcomeUnknown(run_id, target)
                self._verify_run(current, run_id, number, expected_commit, expected_ref, expected_workflow)
                if number == target:
                    remaining = deadline-self.clock()
                    if remaining <= 0:
                        break
                    row = self.attempt(run_id, target, expected_commit, expected_ref=expected_ref,
                        expected_workflow=expected_workflow, timeout=remaining, cancelled=cancelled)
                    return dict(status='accepted', run_id=run_id, run_attempt=target, observation=row)
            except GitHubHTTPError as error:
                if error.status != 404 and not transient(error):
                    raise GitHubOutcomeUnknown(run_id, target) from None
            except GitHubInspectionCancelled:
                break
            except (GitHubUnavailable, GitHubProtocolError, TimeoutError):
                pass
            cancelled.wait(min(poll, max(0, deadline-self.clock())))
        raise GitHubOutcomeUnknown(run_id, target)

    def rerun_failed(self, run_id, expected_commit, *, expected_attempt, expected_ref,
                     expected_workflow, confirmed=False, timeout=60, poll=1, cancelled=None):
        """ONE explicit POST then read-only reconciliation, never a retry policy.

        The caller must durably record its intent before entry. On resume, call
        reconcile_rerun instead; classification/authorization remains project-owned.
        """
        if confirmed is not True:
            raise ValueError('Review and confirm the selected failed-job rerun.')
        self._binding(run_id, expected_attempt, expected_commit, expected_ref, expected_workflow)
        positive(timeout, 'Rerun timeout'); positive(poll, 'Rerun interval')
        cancelled = cancelled or Event(); deadline = self.clock()+timeout
        if cancelled.is_set():
            raise RuntimeError('GitHub rerun cancelled before request.')
        current = self.get(self.base + f'/actions/runs/{run_id}', timeout=timeout, cancelled=cancelled)
        self._verify_run(current, run_id, expected_attempt, expected_commit, expected_ref, expected_workflow)
        if current.get('status') != 'completed' or current.get('conclusion') not in {'failure','cancelled','timed_out'}:
            raise ValueError('Only a terminal unsuccessful reviewed attempt can request failed-job rerun.')
        if cancelled.is_set():
            raise RuntimeError('GitHub rerun cancelled before request.')
        remaining = deadline-self.clock()
        if remaining <= 0:
            raise TimeoutError('GitHub rerun admission expired before request.')
        unknown = False
        try:
            self.request('POST', self.base + f'/actions/runs/{run_id}/rerun-failed-jobs', timeout=min(30,remaining))
        except GitHubHTTPError as error:
            if error.status < 500 and error.status not in {408,429}:
                raise
            unknown = True
        except (GitHubUnavailable, GitHubProtocolError):
            unknown = True
        remaining = deadline-self.clock()
        if remaining <= 0 or cancelled.is_set():
            raise GitHubOutcomeUnknown(run_id, expected_attempt+1)
        result = self.reconcile_rerun(run_id, expected_commit, expected_attempt=expected_attempt,
            expected_ref=expected_ref, expected_workflow=expected_workflow, timeout=remaining, poll=poll, cancelled=cancelled)
        return dict(result, post_response_unknown=unknown)

    def verify(self):
        return self.request('GET', self.base)

    def resolve_ref(self, ref):
        if not isinstance(ref, str) or not ref:
            raise ValueError('Select a published branch or tag.')
        candidates = [('heads', ref), ('tags', ref)]
        for family in ('heads', 'tags'):
            prefix = 'refs/' + family + '/'
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                if not name:
                    raise ValueError('Select a published branch or tag.')
                candidates = [(family, name)]
                break
        for family, name in candidates:
            try:
                row = self.request('GET', self.base + '/git/ref/' + family + '/' + quote(name, safe=''))
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


def credential_token(*, reference='GH_TOKEN', kind='auto', root=None, environment=None):
    """Read an explicit environment-name or existing Git helper; never mutate login."""
    import os
    import subprocess
    environment=dict(os.environ if environment is None else environment)
    if kind not in {'auto','environment-name','credential-helper'}:
        raise ValueError('Unsupported GitHub credential reference kind.')
    if kind!='credential-helper':
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',reference or ''):
            raise ValueError('GitHub token reference must be an environment variable name.')
        token=environment.get(reference)
        if token:return token
        if kind=='environment-name':
            raise ValueError('Selected GitHub credential environment variable is missing.')
    result=subprocess.run(['git','credential','fill'],cwd=root,input='protocol=https\nhost=github.com\n\n',
        text=True,capture_output=True,timeout=30,env=dict(environment,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never'))
    if result.returncode==0:
        saved=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        if saved.get('password'):return saved['password']
    if kind=='credential-helper':raise ValueError('Selected GitHub credential helper has no usable login reference.')
    return None
