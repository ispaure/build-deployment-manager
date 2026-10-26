# Provider extension boundaries

GitHub release policy, TestFlight and Firebase App Distribution remain distinct
project integrations. App Store publication and Google Play publication are
explicitly **Not implemented**. Relevant project settings display that status;
there are no store credential/setup prompts or functional publish controls.
Crafted plans selecting either unavailable provider fail before credentials or
transport access. Legacy serialized plans acquire no new effects from provider names.

The small capability contract names platform/artifact types, status and permitted
credential-reference kinds. Immutable operation receipts identify provider job,
source, artifact checksum and destination for reconciliation. Projects supply
preflight, exact review/effect declarations and read-only outcome reconciliation.
Future store work requires store-specific policy, implementation and real acceptance
before enabling the capability; none is inferred from TestFlight or Firebase success.


## App Store Connect transport

`app_store_connect.AppStoreConnectClient(auth, token_factory=...)` supplies
same-origin `/v1/` JSON requests and pagination. Redirects are refused; foreign
pagination URLs are rejected before signing/authorization. Each request gets a
fresh bearer, the original 30-second HTTP timeout and no automatic retry.
Repeated pagination links fail rather than looping. Error details redact the
current bearer and never print signing material.

`token(auth, now=...)` generates the existing short-lived ES256/P-256 JWT from
an explicitly supplied private-key reference, issuer and key ID. Cryptography
is imported only when signing; an unavailable optional dependency raises
`SigningDependencyError`. Consumers retain their own dependency pins and setup
instructions. Importing this module does not read credentials or load Qt.

`wait_for_processed_build(client, app_id=..., number=..., version=...,
platform=..., timeout=..., interval=..., validate=..., progress=...)` polls the
exact selected build. The caller supplies its audience/expiry validator and
progress presentation. Ambiguous matches, failed processing and exhausted waits
fail visibly. No upload is initiated by polling. Injectable clock/sleep support
portable bounded-wait tests.

App identities, group selection, locale/notes preservation, review/compliance
states, notification choices and additive assignment policy stay with the
project. This transport does not enable App Store publication.

## Firebase CLI transport

`firebase.FirebaseCLI(executable, workspace, environment=...)` invokes an
explicit installed CLI. The project owns installation/bootstrap, private log
location, app/package/group identity checks and credential references. `query`
uses JSON/non-interactive CLI output; malformed or unsuccessful responses raise
`FirebaseError` without echoing potentially private diagnostics. `login` runs
only when the project explicitly requests it, with optional reauthentication.

`distribute(artifact, app_id=..., group=..., release_notes=...,
capture_result=False)` preserves direct console output. With `capture_result=True`
it requires a nonempty JSON operation receipt. Arguments remain structured; paths
and group names are never interpolated through a shell. The client does not
approve an upload, rebuild/sign an artifact or retry an invocation.

## Uncertain writes and project receipts

`providers.ProviderOutcomeUnknown` reports a lost write response or an unusable
Firebase distribution receipt. It is not proof that the remote effect failed.
Callers must reconcile before another attempt. The low-level transports do not
invent a result, automatically authenticate again or replay the mutation.

Projects retain exact artifact/destination review, preflight, durable attempt
markers and receipt persistence. For example, Logistics writes its reviewed
attempt before invoking Firebase delivery and refuses a second invocation while
that attempt is unresolved. The clients do not replace those project gates.

Portable contracts use injected HTTP responses and a harmless local CLI for
pagination isolation, exact waits, private diagnostics and lost/ambiguous writes.
Consumer checks verify the actual generated JWT signature and retained release
policy. No live account login, provider write or native upload acceptance is
implied by these tests.
