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
diagnostics continue. Required failures fail the workflow. Cleanup executes once
after owned running work retires; legacy sequential plans preserve phase order.

Cancellation stops only owned process groups or Windows jobs. The manager never
uses a stale PID to terminate an unrelated process, cancels unrelated hosted jobs,
or stops a VM that predated the run. Project adapters must declare device sequencing
and signing ownership explicitly. A higher worker count does not imply permission
to overlap expensive simulator builds or project-required sequential iOS devices.
Portable overlapping-process tests are generic scheduling evidence, not proof of
concurrent Android/iOS acceptance on unavailable hardware.

Plan-level resource amounts may reserve capacity for an entire owned device
session, while step resources cover build/cache/signing work. Logistics declares a
conservative host mobile-session budget and explicit cleanup dependencies between
iOS devices. Increasing workers alone cannot bypass that sequencing.

POSIX phases may declare a bounded `stop_grace` (default one second, at most thirty)
before group escalation. Logistics mobile helpers use five seconds so their nested
native-tool cleanup can retire its owned groups. Windows uses job termination;
POSIX signal-grace evidence does not establish a Windows graceful-stop path.
