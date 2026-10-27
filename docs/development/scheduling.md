# Bounded scheduling and resource ownership

Plans declare `max_workers` (1–16, default 1), resource amounts and capacities.
Ready independent steps overlap; dependents wait for passed verified outputs.
Device/workspace/signing/cache/build-allocation resource names must be stable
across projects. The manager hashes these names into host-wide private locks,
acquires resources in sorted order, and releases partial acquisitions before waiting.
One persisted host capacity prevents different processes inventing conflicting slot
counts. Capacity changes require explicit reconciliation while idle.

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
