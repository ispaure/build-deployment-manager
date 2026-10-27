# Workflows, review and recovery

## Waiting for a device

Adapters can declare a separate connection check before installation. A temporary
availability failure shows **Waiting to reconnect** and retries automatically
until the selected device returns or you stop the run. The wait releases its
worker and resources between checks, so independent testing, builds, delivery
review and other recipients continue. Stop cancels the wait.

Resume the retained run to reuse passed tests and verified packages. Connection
checks do not approve installation; each recipient still needs review of its exact
package and destination. A signing or identity mismatch stops explicitly. An
interrupted installation has an uncertain outcome and requires reconciliation
before another install; only pre-install availability checks retry automatically.

## Execution and review

A workflow extends an existing versioned plan: dependency-ordered phases declare
commands, output artifact types and effects. The default is sequential. Source,
settings, adapter and toolchain data are captured once. Passing tests never
approves an external effect. Required failed/skipped/unknown dependencies block it.

For a fresh GUI plan, **Start reviewed workflow** authorizes the selected Firebase
and TestFlight uploads and GitHub actions. Release delivery runs after its required
checks and package preparation pass, without a second approval dialog. GitHub
hosted test launches also use Start authorization, then supply their test results
to dependent work. Review shows this scope before
Start. Failed checks still block delivery, and uncertain upload outcomes still
require reconciliation before retry. Existing saved runs keep their original
approval requirements; inspect a fresh plan to use this behavior.

Other explicit per-step upload/deploy/publish effects pause after preparation. Review
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

If the execution process exits before writing a result report, the run summary
shows the final startup error from stderr, when available. The Output tab retains
the traceback with credential redaction. Steps that never started remain queued;
inspect a fresh plan after correcting the startup problem.

Workflow cards show small Windows, Linux, Apple, Android, GitHub and Docker icons
when their declared platform or execution location is known. A card can show both
the target platform and its execution service. Hover for the icon names; the same
context is available to screen readers. Icons describe the affected platform or
service. Passed cards have a green background; failed cards have a red background.
Running cards show a progress bar at the bottom, with completed/total subtasks
when a task count is available. A single running step shows activity without an
invented percentage. Waiting cards stay neutral; cards blocked by a failed
prerequisite are greyed out and remain available for inspection. Status text
also describes the outcome.

Workflow maps start in Horizontal orientation. Use the orientation selector to
choose Vertical or Best fit; your choice stays in effect as the view refreshes
or resizes. Fit keeps the selected orientation.

During a live or retained run, opening a main workflow card shows its relevant
dependency graph. Selecting a step opens the shared inspector alongside the graph;
there is no separate run results browser. Details shows state, waiting reasons,
errors and captured context. Tests, Timing, Output and Files and deliveries stay
scoped to that step; All steps in this card shows the card's combined evidence.
All workflow cards returns to the main overview. View problems opens the failing
step and selects its first reported test problem. External prerequisites and
failed blockers link to their own cards.

Running cards and details use the same elapsed clock. Completed steps keep their
measured durations; skipped steps without measured runtime show Not started.
Main cards show Total step time (may overlap), which differs from active run time
and reported individual test time. Progress updates preserve graph navigation and
Details text selection and scroll position.

Interrupted harmless work is retryable. A running/failed/timeout external effect
has an unknown outcome until its provider reconciles the recorded operation.
The recovery API accepts a project reconciler that returns a verified receipt or
confirms no effect occurred. Unknown effects and their consumers stay frozen;
Continue independent steps can run other eligible branches with their ordinary
artifact reviews. It never retries an unknown action or marks it passed. Each
destination retains its own outcome even if another
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

## Hosted test launches

`dispatch` identifies a remote workflow launch separately from publication,
upload or deployment. Fresh GUI plans authorize GitHub launches through Start;
older saved plans retain separate approval. It uses the same persisted intent and
unknown-outcome reconciliation as other external actions. A checks-only plan can
therefore run hosted tests without selecting a release destination or identifier.
Integrated plans bind dispatch steps to their selected platform and required gates.
For saved plans that still require approval, the UI labels their continuation
“Review and start GitHub checks”. Preparing or viewing a plan never starts a
dispatch; Start authorizes a fresh plan's selected GitHub actions.
