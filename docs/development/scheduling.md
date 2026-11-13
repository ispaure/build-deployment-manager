# Bounded scheduling and resource ownership

Plans declare `max_workers` (1–16, default 1), resource amounts and capacities.
Ready independent steps overlap; dependents wait for passed verified outputs.
Device/workspace/signing/cache/build-allocation resource names must be stable
across projects. The manager hashes these names into host-wide private locks,
acquires resources in sorted order, and releases partial acquisitions before waiting.
One persisted host capacity prevents different processes inventing conflicting slot
counts. Capacity changes require explicit reconciliation while idle.

## Workers inside test phases

`test_workers.reserve(plan, platform, selected, accelerated=...)` lets a project
budget local test phases without changing the Plan schema or its phase scheduler.
The project supplies stable platform IDs and audited runner capabilities. Selected
serial phases reserve one worker; accelerated phases reserve the configured
per-platform ceiling. Both `test-workers:host` and
`test-workers:platform:<platform>` amounts are acquired together with the phase's
existing resources. Two Manager processes therefore share the same limits.

App settings defaults to four workers per platform, limited by the host budget.
The host default is half the available logical CPUs, rounded down, at least one
and at most eight. The per-platform setting accepts 1–8; the host setting accepts
that ceiling through 64. These are test-process reservations, not CPU quotas for
compilers, command helpers, native simulators or unrelated applications. Leave
headroom for those owners. Unsupported runners remain serial; adapters must not
advertise parallel support for native acceptance without separate validation.

Executor validates captured limits under the resource configuration lock before
slot admission, then supplies `BUILD_MANAGER_RESERVED_TEST_WORKERS` only to the
admitted phase. A cooperating runner must never exceed it. Inherited reservations
are removed at each new Manager phase boundary. A phase holds its reservation
through completion and cleanup; unused slots inside a serial part of an audited
runner are conservatively retained. No nested pool may independently multiply
`Plan.max_workers`. Projects retain stage barriers, per-file timeouts, failure
policy and child cleanup, and must allow enough `stop_grace` for their supervisor.

`test_workers.configure` changes only this resource namespace. It excludes
admission while checking every owned worker slot, refuses changes during active
tests, and reconciles persisted capacities while idle. Queued or retained plans
with old capacities fail before launching; prepare a new plan. The setting and
locks use the host's normal Manager configuration root even when a different
project registry is selected. Existing plans with no resource requirements still
perform no resource-directory I/O.

Real subprocess contracts exercise simultaneous independent Manager instances,
shared host and platform ceilings, queued cancellation, unchanged legacy phases,
idle capacity changes and rejection of stale plans. This is portable engine
evidence; it does not establish native Android/iOS concurrency.

## Phase scheduling and cleanup

Plan workspace locks still exclude competing writers to the same workspace.
Parallel branches use separate logs/artifact names; the GUI shows branch states,
waiting reasons and timings. Failed branches block consumers while independent
diagnostics continue. Required failures fail the workflow. Scoped cleanup runs
once its declared prerequisites finish, even while unrelated branches remain active.
Unscoped whole-workflow cleanup still waits for owned running work to retire;
legacy sequential plans preserve phase order.

Cancellation stops only owned process groups or Windows jobs. The manager never
uses a stale PID to terminate an unrelated process, cancels unrelated hosted jobs,
or stops a VM that predated the run. Project adapters must declare device sequencing
and signing ownership explicitly. A higher worker count does not imply permission
to overlap expensive simulator builds or project-required sequential iOS devices.
Portable overlapping-process tests are generic scheduling evidence, not proof of
concurrent Android/iOS acceptance on unavailable hardware.

Plan-level resource amounts can reserve capacity when an entire session truly
owns a shared resource. Logistics no longer reserves one generic mobile session
or orders the complete Android branch after iOS. Its independent platform branches
can overlap within the worker limit; per-step build/cache/workspace/signing locks
serialize actual contention. Explicit cleanup dependencies between successive iOS
devices remain project policy. Increasing workers cannot bypass those dependencies.

Resource contention emits a waiting event with the exact resource ID, amount and
capacity. The GUI records a distinct waiting-for-resource state and names the
resource on the platform card and in the subtask details. Details also list other
steps declaring that resource. Waiting does not start a measured execution clock;
the reason clears when the subprocess actually starts. Whole-workflow resource
waits stay at workflow level rather than creating a fictitious execution step.

Harmless subprocess fixtures prove independent mobile branches overlap, shared
build slots remain exclusive, and scoped cleanup does not stall on an unrelated
branch. These portable contracts do not establish native simultaneous iOS/Android
acceptance or authorize starting a VM, simulator or personal device.

POSIX phases may declare a bounded `stop_grace` (default one second, at most three hundred)
before group escalation. Logistics mobile helpers use five seconds so their nested
native-tool cleanup can retire its owned groups. Windows uses job termination;
POSIX signal-grace evidence does not establish a Windows graceful-stop path.

## Test evidence and live presentation

Trusted project adapters may give an explicit test phase a 64-hex `reuse_key`
covering its complete input contract. The manager stores authenticated receipts
in its private configuration directory. Only successful test outcomes are reused;
retained and original artifact hashes must still match. Misses execute normally.
A hit records original run/step/duration provenance and is displayed as reused,
rather than newly executed. Effects and cleanup cannot declare reuse. Projects
own source, dependency, toolchain and suite identity; the manager never infers
that a changed source is equivalent. Legacy results without such keys are not
automatically imported.

Growing phase snapshots are coalesced before recursive UI redaction and model
updates. Interim-only changes do not rebuild final test/timing trees. Relative
duration bars use a view delegate instead of allocating one widget per case; all
case durations remain available. Native macOS synthetic profiling and portable
contracts cover these paths, not general acceptance of every live provider.

POSIX cancellation retains the declared process-group grace even if its wrapper
exits first, allowing descendants to finish owned cleanup before escalation.

A project may add a structured `reuse_probe` command to recheck its key immediately
before receipt lookup. A failed or differing probe executes tests afresh without
certifying the stale key. Equivalent keyed phases in one plan wait in the pending
queue while the first runs; they do not consume workers blocked on the same
evidence lock. Other independent branches can use those workers.

Owned Windows and Linux guest transports accept an optional advisory `progress`
callback. Host-side heartbeats report elapsed waiting at most every 30 seconds;
a change to invocation receipt reconciliation is reported immediately. These updates
make no additional guest calls, do not invent test counts or guest activity, and
cannot authorize a pass. The exact worker exit/receipt and collected reports stay
authoritative. Presenter failures do not interrupt worker cleanup or change its
outcome. Projects supply user-facing stage labels; headless waiting remains
distinct from observed per-test progress.


## Storage pressure retention

`retention.prune` accepts an optional `max_bytes` allocation budget and
`grace_days`. The caller owns the budget and eligibility policy. When over budget,
recent eligible trees can expire oldest first; the newest `keep` trees, pinned
or durably held trees, active entry locks and grace period remain protected.
The limit is soft when protected storage alone exceeds it. Allocation measurement
skips links and junctions. Dry runs use the same selection as deletion and caller
ownership is rechecked under each entry lock.

Projects may set `keep=0` for explicitly disposable caches or scratch. Cache
groups can use the enclosing build/snapshot lock while retaining packages and
receipts in another group. Explicit user pins still win. The cleanup inventory
includes allocated byte estimates and persistent protection reasons. The UI
counts overlapping parent/cache groups once and separates deletable cache space
from held package storage.

Optional group `protection` callbacks add project-specific protection reasons to
the standard pins and workflow holds. Adopted enclosing checkouts use this to
preserve nested workflow holds. Shared cache budgets count protected allocations
as well as deletable entries. Manual deletion revalidates ownership and path
ancestors after acquiring the entry lock. Unreadable pin/hold state stays protected.

Groups whose ownership depends on metadata declare direct `ownership_files`, such
as a source marker, recipe or Xcode `info.plist`. Removal keeps those files until
bulk content has gone, so interrupted deletion remains identifiable and retryable.
Soft failures also preserve the original retention age. Root markers must remain
ordinary files; linked/missing proof stops removal.

On POSIX hosts, removal can repair a same-owner, non-writable parent directory
inside the selected owned tree, as required by Go's read-only module caches.
It adds owner write/execute permission and retries the failed unlink/removal once.
Linked paths, foreign ownership, parents outside that tree and failures in
already-writable parents remain errors. Retention eligibility, pins, leases and
ownership markers keep their existing protection rules.

`run_retirement.retire_run` serializes with the run supervisor, records retirement
before releasing holds, validates hold paths against the saved plan, and removes
only that run's owner keys. An interrupted retirement is retryable. Recovery and
the executor reject retired runs, including retirement racing with admission.
Executor admission acquires the supervisor lock before reading retained results
and holds it through all report writes. A competing controller cannot overwrite an
active report or replay phases from a stale result read before admission.

The optional `storage_maintenance` adapter action runs through the existing
isolated bridge after CLI execution, only for the original still-trusted
registration and descriptor identity. Project adapters own the roots and policy;
the manager does not sweep shared SDKs, personal simulators or arbitrary folders.
Incomplete maintenance warnings remain separate from the workload outcome and are
visible in status queries and the GUI's results/output.

Linux commands bind a unique invocation to the owned workspace and command digest.
A transport exit 255 retries admission with the same invocation, at most three
times under the original deadline. A lock inherited by the child prevents
concurrent execution; a completed receipt returns the original exit code. An
admission without verified completion fails closed and is never re-executed.
Older staged helpers reject the invocation option before launching a child.
Owned Linux removal waits briefly for invocation locks to retire before deleting
reports. It retains the ownership marker until the content is gone, preserving
retryable cleanup proof when a writer or filesystem error prevents removal.
