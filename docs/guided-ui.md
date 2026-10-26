# Testing and delivery in the guided UI

Select the registered project checkout at the top of the manager. Add its
checkout if necessary; adding a project also authorizes its adapter. Each checkout retains its own settings and
history, even when two checkouts belong to the same project.

Use the visible Add project button to choose a folder. The preview identifies the
project, its platforms and whether its own Python environment exists before you
add it. The newly added project becomes selected. The Project setup panel gives
the next step; missing environments have instructions rather than an empty form.

Use New run to begin. The workflow uses three guided pages, with Back/Next
actions and an explicit Start button. Past runs is separate history navigation.

## Choose work

Choose Validate for checks only, or Validate and deliver for checks, preparation
and reviewed delivery. Projects declaring the [journey contract](journey-contract.md)
offer platform checkboxes and independent destination choices. All selected
platforms' required checks must pass before any delivery. Conflicting choices stay
selected with an explanation; add the required platform or remove the destination.

Older projects retain single-platform validation and Advanced operation, where
their suggested workflows, operation, platform and execution backend are available.
Selecting a suggested workflow explicitly opens Advanced operation. Changes keep
its name with a Modified notice; Restore suggested workflow reapplies its declared
values. No execution host is substituted silently. Applicable named test suites
remain available for single-platform operations. Integrated journeys use the
project's required validation groups rather than a hidden legacy suite selection.

Expand Advanced options to choose a source revision, focused test pattern, build
number override. Source is summarized at all times; release identifiers are visible
in the main form. Open Project settings for persistent local values; run overrides apply
only to this inspection. Next: review plan prepares source and checks
prerequisites asynchronously, then opens Review. It does not start the plan's
commands. Trusted project preparation code remains responsible for its own source
snapshot behavior. Setup contains accounts, test machines, connection checks and
storage cleanup. Connection checks first prepare a reviewable plan.

If Review plan cannot proceed, its explanation appears beside that button. Select
at least one platform for guided validation. Invalid descriptors and changed project identities show a project error. During preparation,
the same area shows progress; failures leave the choices intact for correction.

## Settings

Settings has categories on the left and fields on the right. Search finds fields
by name, category or description without losing edits. Show value sources reveals
profile/default/environment origins when you need them. Unsaved changes are
identified; Save returns to the main window with confirmation. App settings is
separate from project tools and delivery destinations.

App settings controls application text size and explains the workflow. Project
settings opens its loading shell immediately and loads the categorized form, with
navigation on the left and fields on the right. Registered projects need no
additional trust approval, including existing registrations and descriptor updates.
Project reads and writes run in a
worker, with errors, retry and an explicit empty state. You can cancel loading;
real bridge settings requests time out after 30 seconds. Failed saves preserve
input, and closing with unsaved edits asks whether to discard them. Saving locks
the editor until the write completes or reports failure. Changing saved values
invalidates the previous plan review.

## Review and results

Review shows the captured source, selected platform, execution host and planned
work before Start. The work list stays visible; commands and complete plan data
are optional technical details. Uploads and delivery actions are marked as needing
separate approval. A working tree with uncommitted changes is identified explicitly.

Results displays reported test counts, individual cases and measured timing.
Unreported counts are shown as unavailable rather than successful zeroes. Cancel
is available during work, and delivery/retry actions appear only when applicable.
Past runs explains its empty state and enables viewing only after a run is selected.
Viewing a saved run never enables Start for that historical plan.

Use environment variable names, credential helpers or existing protected files.
Credential contents are rejected in profiles, bridge settings writes and saved
plans. New signing/reference files selected through project settings must be outside
the checkout and any Git repository, including ignored paths. Existing pointers
are retained while editing unrelated fields; no credential files are copied or
moved by saving settings. Shared accounts and
registration data default to the OS private configuration directory. Tracked
defaults contain non-secret policy and destinations. Trusted adapters remain
responsible for obeying this rule in their own storage and artifact outputs.

## Review

Read the source identity, selected platforms, delivery order and exact destination
identities. Show technical steps and complete plan reveals the dependency board. Each step shows
its kind, effect, required/optional status, timeout and dependencies. Complete plan
contains the redacted command configuration for detailed inspection. Changing any
selection requires a fresh inspection. Start validation or Start validation and
preparation starts the retained plan;
legacy whole-plan external operations still ask for explicit confirmation.

## Run and results

Results shows reported test counts and guidance for the next action. Timing
lists measured tests slowest first, with total, average and median durations.
Missing durations are excluded from statistics; summed test time differs from
active run time because parallel work can overlap.

The Step details tab includes every declared phase from the start. Running steps have
independent clocks; completed steps retain measured durations. Select a step for
dependency information, errors, log filename and artifact checksums. Progress
counts finished steps, including failures and skips; it is not a success percentage.
The workflow outcome remains explicit.
Integrated runs also summarize each platform and destination independently.
An accepted upload is not proof of installation or tester availability; inspect
the project's retained receipts for the actual provider state.

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
Select each ready action to authorize; unselected actions remain pending. Independent
approved branches may overlap within the plan's worker/resource limits. Completed
deliveries are retained if another branch fails or has an unknown outcome. This
is coordinated execution, not an atomic multi-provider transaction or rollback.

Changed or missing artifacts stop continuation. Unknown provider outcomes require
reconciliation, so the UI refuses to repeat them. Failed/cancelled runs offer Retry
unfinished steps using the original recovery rules. Required failures block their
dependent deliveries even if another branch succeeded.

## Runs and timing

Runs lists up to 100 recently modified retained reports, one directory level
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
adopting named suites and case reporting. Multi-platform selection requires project
adoption of journey schema 1; the manager never merges independently prepared
plans or guesses shared source/version policy. A new UI does not establish native mobile,
Blender or hosted publication acceptance; see [validation](validation.md).
