# Workflows, review and recovery

A workflow extends an existing versioned plan: dependency-ordered phases declare
commands, output artifact types and effects. The default is sequential. Source,
settings, adapter and toolchain data are captured once. Passing tests never
approves an external effect. Required failed/skipped/unknown dependencies block it.

An explicit per-step upload/deploy/publish effect pauses after preparation. Review
exact source/settings, retained artifact checksums, actual embedded identities and
destinations before approving. Approval is session-only and scoped to the complete
plan and verified prerequisite outputs. A changed or missing original/captured
artifact invalidates approval. Legacy whole-plan external effects retain their
existing explicit confirmation requirement; old plans gain no new provider mapping.

Each run atomically records state transitions and saves its original plan, logs,
artifacts, timings and engine/dependency identity. Resume in the GUI or run
`python -m build_manager PLAN --output RESULT_DIRECTORY --resume`.
After reviewing an awaiting step, use `--resume --confirm --approve-step STEP`.
Passed work is reused after checksum verification; only unsuccessful harmless
steps retry. Manager/dependency or plan identity changes require a new inspection.

The [guided UI](guided-ui.md) offers Configure, Review, Run and results, and
project-owned History. Review and continue delivery opens the current retained
run directly with source/settings and verified artifact evidence in one approval
dialog. Step clocks, declared JUnit cases and failure details remain attached to
their original run. Active duration accumulates across resume attempts; time spent
waiting between attempts for human approval is excluded.

Interrupted harmless work is retryable. A running/failed/timeout external effect
has an unknown outcome until its provider reconciles the recorded operation.
The recovery API accepts a project reconciler that returns a verified receipt or
confirms no effect occurred. The GUI refuses unknown remote outcomes; it never
blindly repeats them. Each destination retains its own outcome even if another
branch fails or the workflow is cancelled.

Application close offers cancellation and waits for owned cleanup. Continuing
execution after GUI shutdown is not implemented. Process IDs alone never authorize
termination. Captured outputs, original prepared artifact directories, workspace
and declared snapshot resources receive durable seven-day holds while awaiting
review/reconciliation. Active runs additionally hold OS leases. Terminal completion
releases only that run's holds. Expired/missing artifacts stop continuation clearly.
Existing .keep pins remain untouched. Project retention policy remains authoritative.


## Remote-controller cleanup grace

A VM controller can declare up to 300 seconds of bounded cooperative shutdown
before the local process group is forcibly retired. This gives it time to stop
its owned guest work, collect evidence and clean up remote files. The default is
still one second; existing plans retain that default when the field is absent.
This grace does not extend a test's execution timeout or authorize unrelated guest
operations. Windows child processes remain owned by their process job.
