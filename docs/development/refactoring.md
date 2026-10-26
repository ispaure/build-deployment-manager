# Refactoring audit — October 25, 2026

Reviewed source: manager `6b727bc8`, with its own commonUtils pin `f2a0cf1`.
This is a source/contract audit and documentation pass. Existing native acceptance
is recorded in [validation](../validation.md); this review does not claim a new
Windows, Fedora, emulator or publication run.

## Assessment

The recommendations below have since been implemented. File digests use the
pinned commonUtils bounded stream helper. A retained, cancellable
`VerifyContinuation` worker performs recovery/artifact checks outside Qt,
carrying the selection revision and exact approval identities. Closing drains
it; changed selections discard its result. The CLI rechecks identities after
the dialog and before effect admission.

`ConfigurationView` owns configuration widgets/values; `RunSession` owns the
parented process, buffer, cancellation marker and clocks. `ManagerPanel` retains
planning/review policy and projects into `RunView`. Fresh/resumed admission shares
the session while preserving its distinct approval rules.

CLI approval, executor resume and history now use the bounded `read_report`
loader. Engine/plan/recovery checks remain in their owners. Additive
`--approval-identity STEP=SHA256` binds GUI review to verified prerequisites;
manual CLI approval retains its existing explicit flags. Structured CLI failures
remain visible when an older awaiting-review report exists. All 159 local
portable/offscreen contracts pass, as do native-platform runs on the dedicated
Fedora and Windows guests (three explicit POSIX-only Windows skips). See
[validation scope](../validation.md). The numbered findings retain starting evidence.

The generic/project boundary is sound: registration, isolated adapter execution,
Plan/Phase contracts, scheduling, review/recovery and retention mechanics are
separate owners. The headless engine has no Qt dependency. `RunView`, storage,
VM and account UI already have separate modules. The next work should address
specific remaining costs rather than re-extract the manager or merge it into a
consumer.

## 1. Bound artifact hashing and move review verification off the GUI thread

Evidence: [`executor.py`](../../Python/build_manager/executor.py) captures artifact
digests with `destination.read_bytes()`; [`workflows.py`](../../Python/build_manager/workflows.py)
reads both retained and original files in `verify_artifacts`. The panel's
`resume_workflow` calls `recover` synchronously, which verifies passed artifacts;
approval also computes prerequisite identities synchronously.

The consequence scales with artifact size: each complete file is allocated during
hashing, and reviewing large retained outputs can block the Qt event loop. This
review did not benchmark a multi-gigabyte artifact or reproduce an out-of-memory
failure. The source establishes the unbounded read and synchronous call path.

Reuse the pinned commonUtils `runtime.streams.file_sha256` for file digests.
Introduce one verification result carrying the plan/selection identity, then do
the expensive read in a retained worker. Keep the final checksum recheck at effect
admission: a background preview must not become a permanent approval cache.
Preserve verification of both original and retained artifacts and existing digest
values. Do not change tree-digest semantics to a plain file hash.

Acceptance: equivalent digests on large/changing/missing files; bounded reads;
cancellation; a responsive review panel; changed selections discard late results;
changed artifacts still block continuation. Start with `tests/test_workflows.py`,
`test_executor.py`, `test_guided_ui.py` and `test_workflow_ui.py`.

## 2. Separate panel construction from run-session orchestration

[`ui.py`](../../Python/build_manager/ui.py) is 900 lines at this review.
`ManagerPanel.__init__` assembles controls and wires preparation, history, process,
timing and review state in one 196-line method. `run_plan` and `resume_workflow`
repeat process-admission setup while deliberately differing in approval/recovery.

First extract configuration controls with a selection value/event, then a run
session owner for process, buffers, cancel path and timers. Keep approval decisions
and `RunView` projections explicit. A UI mixin sharing the same mutable panel
would only move lines. Do not unify fresh and resumed commands before preserving
their distinct effect and artifact checks.

Acceptance: preset invalidation, late preparation, selected suite forwarding,
read-only history, declined review, resume reuse, process error and close-during-
history behavior remain covered. Preserve explicit native Qt parenting; the recent
Windows shutdown fix is a completed correction, not a reason to loosen ownership.

## 3. Consolidate retained-result loading before extending its schema

The executor's resume path reads JSON directly; the GUI/history path uses
[`history.read_report`](../../Python/build_manager/history.py), with size and
shape/timing validation. Recovery then has its own plan/artifact checks.
The layers serve different purposes, but loading constraints can drift.

Use one GUI-free result loader for common bounds/schema validation, then retain
executor-specific engine identity and recovery checks. Preserve old timing records
and accumulated attempts. Malformed/missing reports must remain explicit failures,
not a successful empty history or an invitation to rerun an uncertain upload.

Acceptance: the same malformed, oversized and legacy reports through CLI resume
and GUI history; unchanged valid old results; engine/plan mismatch rejection;
unknown provider outcomes still require reconciliation. This is a consistency
improvement, not a claim of an exploitable parser defect.

## Work that should stay separate

Project snapshot staging, source-policy checks, native suite inventories and
release gates belong in adapters. Windows durable invocation receipts and POSIX
process groups have different semantics; do not replace them with a common retry
loop. Project pruning policy stays outside the reusable retention mechanism.
Linux/Windows Android support remains intentionally unavailable as documented in
[host capabilities](../hosts.md), pending its own implementation and native proof.

Recommended order: artifact verification first, panel boundaries second, result
loading third. Each change should keep saved Plan/Phase fields stable and finish
with focused generic and consumer checks before a new manager pin is adopted.

[Developer guide](development.md)

## Validation of this review

All 154 manager contracts pass on the local macOS host with offscreen Qt. The
developer guide's harmless plan executes through the actual CLI and produces a
passing retained result in a disposable directory. All 16 manager wiki pages
pass H1, relative-link/heading and explicit landing/child-link checks. Generic
contracts and controlled transport fixtures do not establish a new Windows,
Fedora, device or hosted-publication acceptance run.

## Final cancellation-safe runtime

Runtime `9225924` adds structured cancellation during captured-artifact hashing,
so a cancelled stream still records its outcome and runs owned cleanup. All 159
contracts pass on macOS, dedicated Fedora and dedicated Windows; Windows retains
three explicit POSIX-only skips. Both guest workspaces are removed after report
collection. The preceding `bb34d5f` evidence remains the original owner-refactor
checkpoint.
