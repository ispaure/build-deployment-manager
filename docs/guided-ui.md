# Testing and delivery in the guided UI

Select the registered project checkout at the top of the manager. Add and trust
its descriptor first if necessary. Each checkout retains its own settings and
history, even when two checkouts belong to the same project.

## Configure

Choose a project workflow preset for an integrated journey, or choose Custom
operation, platform, operation and backend. An unavailable preset stops with an
explanation; it never substitutes another execution host. Project-declared test
suites appear only for applicable platform/operation combinations. The default
retains the project's full-suite behavior. Changing a preset's selections turns
it into a custom operation and invalidates the previous review.

Expand Advanced options to choose a source revision, focused test pattern, build
number override or release identifier. Open Settings for persistent local values;
run overrides apply to this inspection. Inspect plan prepares source and checks
prerequisites asynchronously, then opens Review. It does not start the plan's
commands. Trusted project preparation code remains responsible for its own source
snapshot behavior.

## Review

Read the source identity, settings/destinations and ordered steps. Each step shows
its kind, effect, required/optional status, timeout and dependencies. Complete plan
contains the redacted command configuration for detailed inspection. Changing any
selection requires a fresh inspection. Run reviewed plan starts the retained plan;
legacy whole-plan external operations still ask for explicit confirmation.

## Run and results

The Steps tab includes every declared phase from the start. Running steps have
independent clocks; completed steps retain measured durations. Select a step for
dependency information, errors, log filename and artifact checksums. Progress
counts finished steps, including failures and skips; it is not a success percentage.
The workflow outcome remains explicit.

The Tests tab shows individual cases when a phase supplies a declared JUnit report.
Search case/suite/class names and messages, or filter by Problems, Passed or
Skipped. Select a case to read its failure/skip detail and measured duration.
Adapters without individual reports still show complete phase status and logs.
Cases appear after report capture at phase completion; Live output streams during
execution. Console text is never treated as proof that a case passed.

Cancel operation requests cancellation and owned cleanup. Closing the application
during active work offers the same cancellation path. Open results and logs opens
the project-owned evidence folder.

## Continue delivery in one session

An integrated project plan can test, build and prepare delivery in one run. When
it reaches an external upload/deploy/publish phase, it pauses for review. Select
Review and continue delivery to see the original source/settings, destination and
verified retained artifact paths/checksums together in the approval dialog.
Cancel is the default. Approval continues the same result directory and reuses
passed preparation after checksum checks; it does not rebuild and relabel artifacts.
Further external phases may require another review when their prerequisites finish.

Changed or missing artifacts stop continuation. Unknown provider outcomes require
reconciliation, so the UI refuses to repeat them. Failed/cancelled runs offer Retry
unfinished steps using the original recovery rules. Required failures block their
dependent deliveries even if another branch succeeded.

## History and timing

History lists up to 100 recently modified retained reports, one directory level
under the selected project's result root. Refresh updates it without blocking the
window. View selected run restores its step board, cases and original plan for
read-only inspection. Viewing history disables starting a new run from stale
selections. Resume retained workflow also accepts a manually selected result.json.

Step duration measures that phase. Active time is accumulated supervisor execution
time across attempts, including execution/resource waits and cleanup, excluding
time between attempts spent awaiting human review. Each new attempt is recorded
separately. Reports written before attempt tracking retain their original recorded
time as the starting total; missing historic attempt details are not reconstructed.

## Project integration

The manager supplies no hard-coded Logistics or Blue Hole release commands.
Projects implement presets, suites, reports and dependency gates under the
[test organization contract](test-organization.md). They retain native runtimes,
source policy and destinations. Their current descriptors continue to work while
adopting named suites and case reporting. A new UI does not establish native mobile,
Blender or hosted publication acceptance; see [validation](validation.md).
