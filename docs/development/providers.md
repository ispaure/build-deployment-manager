# Provider extension boundaries

Linux guest transports use a separate local process session so adapter cancellation
can stop the token-owned guest workload before retiring its transport and collecting evidence.

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


## GitHub attempt recovery

`github.GitHub.get` retries only transient GET failures within its selected read
budget. HTTP status, unavailable transport and unusable JSON have distinct safe
exception types; provider bodies and signed URLs are not included in errors.
Existing dispatch and wait APIs remain available.

`attempt` and `wait_attempt` require the exact run, attempt, commit, ref and workflow.
They verify repository identity and use the attempt endpoint rather than trusting
an older parent-run conclusion. A queued aggregate remains queued even when its
currently visible jobs have finished. A project may separately verify its own
fixed workflow's complete terminal-job witness; the generic client does not infer
that an arbitrary workflow is complete. Cancelling this observation sends no
provider write.

A caller must persist its reviewed intent before `rerun_failed`. That method
validates inputs and cancellation before issuing exactly one failed-jobs POST,
then observes the expected next attempt. An HTTP 500 or lost response can still
mean the request was accepted. `GitHubOutcomeUnknown` retains the run and expected
attempt when acceptance cannot be established, including observation timeout or
cancellation after the write. Resume with GET-only `reconcile_rerun`, never by
repeating the POST. Source/ref/workflow mismatch remains a policy failure, without
removing the caller's unresolved intent. Job-failure classification and permission
to rerun remain project responsibilities; there is no automatic test-failure retry.

`job_log` reads one private job log with a byte cap and total deadline. It accepts
one HTTPS redirect to approved GitHub Actions/Azure blob storage, using a fresh
anonymous request without forwarding API authorization. Further redirects,
chunked transfer framing and streams lacking deadline-aware socket reads fail
closed. Callers retain only the evidence and redacted classification they need;
raw logs and signed URLs do not belong in public receipts or documentation.

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
portable bounded-wait tests. Transient read-only connection failures and HTTP
429/500/502/503/504 responses during this poll retry the same exact lookup within
the original deadline. Authentication, malformed responses and policy failures
still stop immediately; uploads and other writes are never retried by polling.

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
it accepts a nonempty JSON operation receipt or an explicit successful void-command
envelope with exit zero. Firebase CLI 15.34's distribution command awaits the
provider operations but returns no result object; this produces
`{cli_status: "success", receipt_kind: "completed-command"}`. That receipt does
not invent a remote release ID. Missing/invalid success, nonzero exit and
ambiguous result objects remain uncertain. Arguments remain structured; paths
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
