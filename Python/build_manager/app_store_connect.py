"""Reusable App Store Connect signing and HTTP transport; no project destinations."""
import base64
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .providers import ProviderOutcomeUnknown
from .redaction import Redactor

API = 'https://api.appstoreconnect.apple.com'


class SigningDependencyError(ValueError):
    """The caller's provider environment lacks the optional signing dependency."""


def token(auth, now=None):
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
    except ImportError:
        raise SigningDependencyError('Install cryptography in the provider environment for App Store Connect signing.') from None
    key = serialization.load_pem_private_key(Path(auth['key_path']).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('The App Store Connect key must be a P-256 EC private key.')
    now = int(time.time() if now is None else now)
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')
    header = encode(json.dumps({'alg': 'ES256', 'kid': auth['key_id'], 'typ': 'JWT'}, separators=(',', ':')).encode())
    payload = encode(json.dumps({'iss': auth['issuer_id'], 'iat': now - 10, 'exp': now + 600,
                                 'aud': 'appstoreconnect-v1'}, separators=(',', ':')).encode())
    message = header + b'.' + payload
    r, s = utils.decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
    return (message + b'.' + encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))).decode()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AppStoreConnectClient:
    def __init__(self, auth, *, token_factory=token):
        self.auth = auth
        self._token = token_factory
        self.opener = build_opener(NoRedirect())
        # Validate the key locally before an upload can start.
        self._token(auth)

    def request(self, method, path, *, params=None, body=None):
        url = path if path.startswith('https://') else API + path
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.appstoreconnect.apple.com' or not parsed.path.startswith('/v1/'):
            raise ValueError('Refusing an API URL outside App Store Connect.')
        if params:
            url += ('&' if parsed.query else '?') + urlencode(params)
        bearer = self._token(self.auth)
        request = Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                          headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            # Log Apple's error descriptions, never JWTs or private-key material.
            try:
                errors = json.loads(error.read()).get('errors', [])
                detail = '; '.join(str(e.get('detail') or e.get('title') or e.get('code')) for e in errors)
            except (ValueError, AttributeError, TypeError):
                detail = 'See the App Store Connect build and beta review information.'
            detail = Redactor((bearer,))(detail)
            raise RuntimeError(f'App Store Connect HTTP {error.code}: {detail}') from None
        except (URLError, TimeoutError, OSError):
            if method.upper() not in {'GET', 'HEAD'}:
                raise ProviderOutcomeUnknown('App Store Connect outcome is unknown. Reconcile this operation before retrying; do not re-upload the build.') from None
            raise RuntimeError('Could not reach App Store Connect. Retry the lookup; do not re-upload the build.') from None

    def list(self, path, **params):
        result = self.request('GET', path, params=params)
        items = list(result['data'])
        seen = {path}
        while result.get('links', {}).get('next'):
            following = result['links']['next']
            if following in seen:
                raise RuntimeError('App Store Connect pagination repeated a page.')
            seen.add(following)
            result = self.request('GET', following)
            items.extend(result['data'])
        return items


def wait_for_processed_build(client, *, app_id, number, version, platform, timeout, interval,
                             validate=lambda build: None, progress=lambda: None,
                             sleep=time.sleep, clock=time.monotonic):
    """Poll one exact build; the caller validates its audience/expiry policy."""
    if timeout <= 0 or interval <= 0:
        raise ValueError('Build processing wait limits must be positive.')
    deadline = clock() + timeout
    while True:
        builds = client.list('/v1/builds', **{'filter[app]': app_id, 'filter[version]': number,
                            'filter[preReleaseVersion.version]': version,
                            'filter[preReleaseVersion.platform]': platform, 'limit': 200})
        if len(builds) > 1:
            raise ValueError('Multiple builds match the exact app, platform, version and build number.')
        if builds:
            build = builds[0]
            attrs = build['attributes']
            validate(build)
            state = attrs['processingState']
            if state == 'VALID':
                return build
            if state != 'PROCESSING':
                raise ValueError('Apple build processing stopped with state ' + state + '.')
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError('Apple is still processing this build. Run distribute again later; do not re-upload.')
        progress()
        sleep(min(interval, remaining))
