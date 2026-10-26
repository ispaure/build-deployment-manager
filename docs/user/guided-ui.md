# Testing and delivery in the guided UI

Select the registered project checkout at the top of the manager. Add its
checkout if necessary; adding a project also authorizes its adapter. Each checkout retains its own settings and
history, even when two checkouts belong to the same project.

Use the visible Add project button to choose a folder. The preview identifies the
project, its platforms and whether its own Python environment exists before you
add it. The newly added project becomes selected. A setup notice appears only when the project environment needs attention.
Project settings has one toolbar entry; setup does not repeat it.

Use New run to begin. The workflow uses three guided pages, with Back/Next
actions and an explicit Start button. Past runs is separate history navigation.

## Choose work

Configuration uses two resizable columns. Source, Testing, Delivery and Advanced
tabs keep settings compact on the left. Testing presents a platform checkbox and
execution-location dropdown in each table row. The live workflow overview fits on
the right; use Fit or the zoom controls to inspect larger maps. Selecting a card
opens its matching configuration tab and destination category.
Changing selections adds and removes branches immediately; missing platform
requirements stay visible as amber cards without selecting them on your behalf.

The map is explicitly a high-level proposal, not a verified executable plan.
It is built from the selected intent and descriptor metadata, without calling the
project planner or inspecting source on each edit. Review resolves exact source,
build/test substeps, dependencies, hosts and resource limits. Repeated proposal/planned badges are hidden in the overview; Run cards show
actual execution status. Source choices never commit, push or deploy anything.

Source is visible up front: Current files includes edits; Latest commit selects
HEAD and excludes edits; Specific commit, branch or tag accepts an explicit Git
revision. Changing execution hosts no longer silently switches source. Source
policy is checked during Review, and committed-source failures reopen Source with
an explanation. The integrated contract currently requires selected validation;
the UI shows that requirement rather than offering unsupported bypass controls.

Choose Validate for checks only, or Validate and deliver for checks, preparation
and reviewed delivery. Projects declaring the [journey contract](../development/journey-contract.md)
offer platform checkboxes and independent destination choices. Selecting a
destination expands its description, notes and recipient inputs directly below
its checkbox, before the next destination. Deselecting keeps typed text for later
but excludes it from submitted run inputs. Fields shared by several destinations
appear once in the shared run options. Advanced operations keep their own inputs. Each destination waits for its own required platforms. A failure on an unrelated
platform does not block its delivery review. Conflicting choices stay
selected with an explanation; add the required platform or remove the destination.

Older projects retain single-platform validation and Advanced operation, where
their suggested workflows, operation, platform and execution backend are available.
Selecting a suggested workflow explicitly opens Advanced operation. Changes keep
its name with a Modified notice; Restore suggested workflow reapplies its declared
values. No execution host is substituted silently. Applicable named test suites
remain available for single-platform operations. Integrated journeys use the
project's required validation groups rather than a hidden legacy suite selection.

Source selection is in its own section. Use Advanced for a focused
test pattern, build number override or optional custom release identifier. Open Project settings for persistent local values; run overrides apply
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

## Settings versus this run

Project settings stores reusable tools, accounts, signing references, app identities
and default destinations. Its “Defaults for new runs” section seeds delivery fields.
Choose the platform, execution location, source, destination and optional build
number for each run. TestFlight “what to test” and recipient group, and Firebase
notes/group appear with the applicable delivery choice. Editing these run fields
never saves over project defaults. Review displays the captured run values.

Projects supporting selectable execution locations show a location beside each
platform: macOS can run on GitHub while iOS uses local simulators, for example.
Choosing GitHub explains its committed-source requirement. Select Latest commit
or a specific revision explicitly to exclude local edits.
GitHub checks need no release identifier: launching checks is a separately reviewed
external action, distinct from publishing. Native tester delivery can still require
local native receipts; unsupported combinations explain that prerequisite.

Configuration settings and the proposed map scroll independently; the window
can also scroll on shorter displays. Advanced options contains an optional custom release identifier.
Leave it blank for the owning project's automatic naming policy. The suggested
identifier is based on project version and local tags; publication rechecks remote
availability. Preparing a suggestion does not create or reserve a remote tag.

## Review and results

Review shows the captured source, selected platform, execution host and planned
work before Start. The exact dependency map stays visible; commands and complete plan data
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

Read the source identity, selected platforms and exact destination identities.
The dependency map shows cards on the left and an inspector on the right. Arrows
show prerequisites; branches can overlap when worker and shared-resource limits
allow. Select a card to inspect prerequisites, outputs and approval requirements.
Whole workflow restores the overall review. Selecting cards executes no code.
Show technical details and complete plan reveals the dependency table and commands. Each step shows
its kind, effect, required/optional status, timeout and dependencies. Complete plan
contains the redacted command configuration for detailed inspection. Changing any
selection requires a fresh inspection. Start validation or Start validation and
preparation starts the retained plan;
legacy whole-plan external operations still ask for explicit confirmation.

## Run and results

The same dependency map stays visible during execution. Click a card to scope
Results, Tests, Timing and Output to that step. Whole workflow restores combined
totals. Switching cards preserves the open inspector tab. The splitter can be
resized; larger maps scroll in both directions. Cards support Tab and Space.

Card text and colored edges identify running, passed, failed and approval states.
A failed prerequisite immediately mutes affected pending descendants and explains
why they will not run. This is a display prediction, not a new execution result;
the executor later records skipped steps. Muted cards remain selectable. Cleanup
steps declared to run after failure remain eligible, and unrelated branches stay
independent.

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
execution. Output is scoped to the selected card; unassigned runner messages
appear under Whole workflow. Saved runs can preview each step’s retained log
within its own result directory. Console text is never treated as proof that a case passed.

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
[test organization contract](../development/test-organization.md). They retain native runtimes,
source policy and destinations. Their current descriptors continue to work while
adopting named suites and case reporting. Multi-platform selection requires project
adoption of journey schema 1; the manager never merges independently prepared
plans or guesses shared source/version policy. A new UI does not establish native mobile,
Blender or hosted publication acceptance; see [validation](../development/validation.md).

## Development devices and delivery groups

Delivery groups project-declared destinations into tester platforms, development
devices, stores and source releases where supported. Store submission is not
implemented by Logistics and is explicitly labelled unavailable. Firebase and
TestFlight share one tester message while retaining separate recipient groups.

For Logistics, choose Delivery → Dev devices, enable Android test devices or
iPhone / iPad, then check specific saved devices. Reload reads saved metadata;
it does not scan, connect, wake or pair devices. Add ID accepts an already paired,
connected Android serial or iOS UDID when the saved list lacks that device.
Nothing is selected automatically. Availability is checked at installation.
Selections remain when switching tabs and are omitted when their destination is
deselected. Each selected device appears as a separate install card.

The project captures one source snapshot, runs its required platform checks,
prepares a development APK or signed device-app archive, then pauses for review
before each installation. The reviewed package is installed in place, without
uninstalling, clearing app data, automatic re-signing or silently switching devices.
Signature, provisioning, version and connection failures stop that target.
Unknown installation outcomes require reconciliation before retrying.
Device-only Logistics delivery can use captured current files; GitHub/Firebase/
TestFlight retain their committed-source and complete release-acceptance policies.
Local device delivery currently requires the configured Mac build environment.
Native builds and personal-device installation acceptance require separate runs;
portable contract tests and offscreen layout checks do not establish those results.

## Reading shared build workflows

Read the workflow from left to right under Source, Testing and Delivery headings.
Delivery can span several columns: build, export/sign and delivery to each
recipient. Cards stay near their parents; a shared build appears once and branches
to its consumers when the project declares package metadata.

Logistics device destinations offer Debug (default) and Release. Debug prepares a
separate development app. Release reuses the signed Firebase APK on Android, or
exports a separately provisioned iOS device app from the shared Release archive.
Each device still has its own reviewed installation. Release packaging requires
committed source, the existing release signing setup and full release gates.

The overview explains source requirements for selected destinations. Current files
can be used for local tests and Debug device delivery. GitHub releases, tester
services and Release device packages require committed source. Latest commit
excludes edits without committing them; GitHub releases also require a clean
checkout matching that commit. Selecting a source never commits or pushes it.
