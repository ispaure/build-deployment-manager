# Testing and delivery in the guided UI

Select the registered project checkout inside the current run tab. Add its
checkout if necessary; adding a project also authorizes its adapter. Each checkout retains its own settings and
history, even when two checkouts belong to the same project.

Use Add your first project, or More → Add project, to choose a folder. The preview identifies the
project, its platforms and whether its own Python environment exists before you
add it. The newly added project becomes selected. A setup notice appears only when the project environment needs attention.
Each run tab owns its project picker, Project settings, More and Help controls;
there is no shared project toolbar above the tabs. Setup does not repeat Project
settings. The picker shows project names; hover to see the checkout path. Duplicate names
include their paths. More contains project registration, setup, cleanup and app
settings; Help remains directly available.

The first run opens in a tab. Use + to open another independent run, keeping the
previous run’s project, choices, progress and results available. Tabs can use
different projects. Changing a tab’s project replaces only that tab’s idle run;
its siblings retain their selected projects, drafts, plans and results. Busy tabs
lock their own project controls while other idle tabs remain editable. A new tab
starts with the project of the tab/window where + was used. Project settings and
More actions always target the tab that contains them. Saved settings invalidate
other plans for the same project, without changing other projects.

Drag a tab out or use its context menu to detach it; its project controls travel
with it. Dock it back by dragging or using Dock to Main Window.
The last attached run stays in the main window. Active work must finish before
its tab can close; closing the app offers to cancel active operations and finish
cleanup across all tabs.

Each run has Choose work, Review plan, Progress & results and History navigation,
with Back/Next actions and an explicit Start button. Opening retained results
from History creates another run tab. The action footer stays below the run’s
scrolling content, including when detached. Filled primary-action
buttons follow the app's active accent color and identify the main next action;
Back, Cancel and utilities use neutral
buttons. Settings, project setup and approval dialogs use the same hierarchy.

## Choose work

Run checks, Build only and Prepare and deliver are visible, exclusive goal buttons.
Build only selects a supported Build operation without tests or delivery.
Project operation opens the project operation controls. The Source, Test,
Delivery and Options tab buttons sit above the settings pane; click one to
open its choices. Delivery categories are Tester, Development, Store and Source.
Test and each delivery category show selection counts. Tester and Development
each contain Android and iOS subtabs; selecting a workflow card opens its matching
platform. Development and its platform subtabs count selected devices for enabled
destinations; its total combines Android and iOS devices. Other delivery categories
count selected destinations. Hover for selected names. The active tab remains highlighted.
The workflow overview takes roughly three quarters of the workspace by default;
drag the divider to resize the panes. Requirements appear below both panes,
keeping warning actions outside the tab contents.
Amber repair buttons open the exact source, platform or recipient control that
needs attention and highlight its workflow card. They preserve current choices;
select the required value explicitly. Source repairs use declared project policy
or the selected execution host, without committing or excluding files for you.
Switching to Run checks excludes delivery without discarding saved destination
choices; switching back restores their visibility.

Presets appears only in Choose work. Selecting a preset loads its saved choices
and invalidates any previous review; it never starts work. The adjacent menu
contains Save preset and Delete preset. Edits mark the selected preset Modified.
New workflow options inherit their declared defaults without marking an older
preset Modified; changing an inherited option away from its default does.
Saving a preset keeps the current choices and review; deleting one leaves the
current draft intact. Presets remain private to the selected checkout. On reopening the app, choices
that exactly match a saved preset re-select its name without reapplying it.

Configuration uses two resizable columns. The selected section's settings appear
on the left. Test presents a platform checkbox and
execution-location dropdown in each table row. The live workflow overview keeps
cards on the right. The overview defaults to Horizontal; Best fit can choose the
orientation, or select Vertical explicitly. Display controls sit beside the
overview heading in the upper-right corner. Fit shows the complete graph without scrollbars; zoom in
to read a dense graph and scroll or drag to explore it. Follow mouse is disabled
by default and remembers your choice across app launches. Enable it to move
inside a fitted map to enlarge small cards, then move toward
an edge to reach that corner. The map reaches its edge within the outer fifth
of the panel, so you do not need to aim at the border. Source, Testing and Delivery
headings stay readable above their section boxes while you zoom and pan. Their
widths and horizontal positions follow the boxes; offscreen sections scroll out
of the heading strip too. In Vertical view, headings stick along the left edge
and follow each section's height and vertical position.
Leaving the map restores the complete overview.
Turn Follow mouse off for a stationary map; manual zoom also stops following
until you use Fit again. Selecting a card
opens its matching configuration section and destination category.
Changing selections adds and removes branches immediately; missing platform
requirements stay visible as amber cards without selecting them on your behalf.

The map is explicitly a high-level proposal, not a verified executable plan.
It is built from the selected intent and descriptor metadata, without calling the
project planner or inspecting source on each edit. Review resolves exact source,
build/test substeps, dependencies, hosts and resource limits. Repeated proposal/planned badges are hidden in the overview; Run cards show
actual execution status. Source choices never commit, push or deploy anything.

Preview cards list their prerequisites. Optional device builds connect only to
selected checks for the package's declared platforms; selecting Windows checks
does not make them prerequisites of an iOS build. Package dependencies carry
their checks forward to later signing/export steps. Different prerequisite sets
use separate connector rails; dots mark junctions within a shared set.
Hover a card to emphasize it, its prerequisites and its downstream execution steps.
Unrelated cards and their connections remain visible in gray, in both light and
dark themes. Sibling branches sharing an ancestor stay gray unless they are also
upstream or downstream of the hovered card.
Moving away restores the complete map without changing selection.
Keyboard tab focus provides the same trace. Completion waits are included and
keep their dotted lines.
The full card, including its labels and icons, activates the hover trace.
Floating tooltips are suppressed inside the map so they cannot interrupt the
trace or cover adjacent cards; select a card to inspect its details.
Exact host checks are resolved during Review and can be inspected in the side
pane. A shared executable step keeps one identity across dependent branches;
distinct steps remain distinct even when their labels or execution hosts match.
The preview does not decide whether host checks can be reused or must repeat.

Source is visible up front: Current files includes edits; Latest commit selects
HEAD and excludes edits; Specific commit, branch or tag accepts an explicit Git
revision. Changing execution hosts no longer silently switches source. Source
policy is checked during Review, and committed-source failures reopen Source with
an explanation. Routine editing and card selection do not add footer messages.
Unresolved choices appear as requirement buttons; source conflicts explain the
next step beside Build from and disappear when resolved. Additional source and
release-policy details are available in that control's tooltip and accessibility
description. A clean-checkout policy is verified during Review rather than shown
as a warning before the checkout has been inspected.
The integrated contract currently requires selected validation;
the UI shows that requirement rather than offering unsupported bypass controls.

Choose **Run checks** for checks only, or **Prepare and deliver** for checks, preparation
and reviewed delivery. Projects declaring the [journey contract](../development/journey-contract.md)
offer platform checkboxes and independent destination choices. Selecting a
destination expands its description, notes and recipient inputs directly below
its checkbox, before the next destination. Deselecting keeps typed text for later
but excludes it from submitted run inputs. Fields shared by several destinations
appear once in the shared run options. Advanced operations keep their own inputs. Each destination waits for its own required platforms. A failure on an unrelated
platform does not block its delivery review. Conflicting choices stay
selected with an explanation; add the required platform or remove the destination.

Older projects retain single-platform validation and **Project operation**, where
their suggested workflows, operation, platform and execution backend are available.
Selecting a suggested workflow explicitly opens Project operation. Changes keep
its name with a Modified notice; Restore suggested workflow reapplies its declared
values. No execution host is substituted silently. Applicable named test suites
remain available for single-platform operations. Integrated journeys use the
project's required validation groups rather than a hidden legacy suite selection.

Source selection is in its own section. Use Advanced for a focused
test pattern, build number override or optional custom release identifier. Open Project settings for persistent local values; run overrides apply
only to this inspection. Next: review plan prepares source and checks
prerequisites asynchronously, then opens Review. It does not start the plan's
commands. Trusted project preparation code remains responsible for its own source
snapshot behavior. More contains accounts, test machines, connection checks and
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
GitHub checks need no release identifier. Start authorizes their hosted launch
in a fresh reviewed plan. Native tester delivery can still require
local native receipts; unsupported combinations explain that prerequisite.

Configuration settings and the proposed map scroll independently; the workspace
can also scroll on shorter displays while the action footer stays visible.
Advanced options contains an optional custom release identifier.
Leave it blank for the owning project's automatic naming policy. The suggested
identifier is based on project version and local tags; publication rechecks remote
availability. Preparing a suggestion does not create or reserve a remote tag.

## Review and results

Live and retained runs keep the main workflow cards visible. Select a card to
filter the persistent task list and inspector beside it, then select a step for
evidence. Card selection does not open a nested dependency-card browser.
The inspector's Files and deliveries tab lists relevant destination outcomes and
retained output paths. A successful run preserves your current view; partial
delivery and unknown outcomes remain separate.
Prepared input files from prerequisite steps are included with the delivery
that consumes them; inspecting a file opens its producing step.

During execution, Running, Queued, Waiting for capacity and Needs approval counts
open their relevant step. Cancelling shows Stopping until the retained result
arrives; it does not imply that cleanup has already finished.

History supports search and All runs, Needs attention and Completed filters.
Outcome icons and a Next step column distinguish approvals, failures and unknown
provider outcomes. Refresh preserves the selected run; viewing remains separate
from retrying or approving it.

The platform Find shortcut focuses search in History, Project settings and the
individual Tests tab. Approval choices support Space and Escape; highlighted
buttons retain visible keyboard focus. Activity controls wrap in narrow windows.

Cancelling delivery approval returns to the retained run with its review action
available. Selecting one destination leaves other approvals pending. Completed
delivery summaries show destination and retained-file counts; output selections
and expanded groups remain stable while other work updates.

Review and Progress & results use the same workspace: the captured workflow
cards stay on the left, with a persistent task list and inspector on the right.
Captured source and run choices expand above it. The overview preserves the
Source, platform, preparation and destination cards from Choose work. Selecting
any card filters the side pane to its tasks; it never opens another card map.
All tasks restores the complete task list. The tree groups work by workflow card,
then task, test folder, file and individual test. Start carries the selected card,
task and pane sizes into Progress & results, where states and timing update in
place. Back to choices and Start stay below the review workspace.

Results displays reported test counts, individual cases and measured timing.
Unreported counts are shown as unavailable rather than successful zeroes. Cancel
is available during work, and delivery/retry actions appear only when applicable.
An attention area above the workflow names failed steps and pending approvals.
View problems finds failed tests across the whole run, clearing unrelated search,
or selects the failed step when no individual report exists.
Unknown outcomes take priority and open their step evidence for reconciliation.
Review delivery uses the same retained-evidence verification and explicit approval
dialog as the footer; it stays disabled while active work or verification prevents
continuation. Independent failures and ready approvals can appear together.
History explains its empty state and enables viewing only after a run is selected.
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

Read the captured source, selected platforms and exact destination identities.
Expand Captured source and run choices to see the full source identity and captured
notes and recipients. Click an overview card to inspect its execution steps.
The overview stays visible; All tasks restores the full list in the side pane.
Select a task in that list to show its prerequisites, execution location, timing
and declared outputs. Prerequisite buttons
open the relevant step, including across card boundaries. Unmapped work remains
available through Other resolved subtasks.

The task table shows — until measured time exists, with Not started in its
tooltip. Repeated platform and validation prefixes are shortened so task names
remain distinguishable; their tooltips retain full identities. Review does not
manufacture elapsed times or historical estimates. The selected step shows compact
fields and prerequisite buttons rather than a text dump; timeout, required flags
and resource settings remain in the Command tab. Output filenames
keep their full paths in tooltips.

When evidence is present, failed task rows carry an error icon. View error details
above the workspace opens the failing step even when another card is selected.
Its Error details panel appears automatically, with the error headline, full
traceback, exit code, failed test messages and captured step output. Successful
and unstarted steps have no empty error box. View blocking step follows a blocked
step back to the recorded failure. Changing unrelated facts preserves selected
text and scroll position in the details. A plan-preparation failure exposes Error
details with the full redacted traceback beside the retained choices.

The right inspector uses Details, Command and Plan tabs. Details presents labelled
task facts, prerequisite controls and available error evidence. Command shows the
exact selected step command, working directory and environment references. Plan
contains Summary, Dependencies and Data views for the complete reviewed plan.
The task/test tree and details tabs occupy independently resizable vertical panes,
with no outer scrolling sidebar. Each pane scrolls its own content. Selecting tasks or tabs starts no
commands.

Fit shows the entire graph without scrollbars, scaling down when necessary.
Zooming switches to a pannable view for inspecting dense graphs.
Map interaction help is available in its tooltip rather than permanent instruction
paragraphs. The footer keeps the approval boundary beside Start.
Choose work, Review and Run maps offer Best fit, Horizontal and Vertical.
Best fit switches between left-to-right and top-to-bottom when that fits the
window better. Small workflows stay compact and aligned near the top.
Source, Testing and Delivery
use soft background tints rather than divider lines that resemble connections.
Keyboard focus brings off-screen cards into view. Connections stay visible when
selecting a step; selection changes the details, not which arrows appear.
Steps sharing the same prerequisites use a shared junction instead of crossing
arrows. Every incoming prerequisite at that junction is required.
Arrows show prerequisites;
branches can overlap when worker and shared-resource limits allow. The map omits
redundant success arrows: if A → B → C already shows a requirement, it hides the
extra A → C arrow. Details and the dependency table retain every declared
dependency. Cleanup arrows also omit waits already implied by intervening steps
finishing. A cleanup or completion-only path never hides a required success gate.
Dotted arrows wait for completion without requiring success.
Cleanup runs even after failed tests. Its completion therefore does not imply
that those tests passed: final validation keeps its separate success requirements.

Projects can declare test-file inventories in the reviewed plan, making files
browsable before execution. Individual tests appear as the runner discovers and
reports them; a file list does not promise that all cases are already known.
Folders such as appearance expand once to reveal file basenames rather than
repeating truncated paths on every row. Full paths remain in tooltips.
The Logistics host runner reports the current test immediately at its start,
followed by its outcome and measured duration. The task card and Details pane also
show the current test. Runners without live events still update from intermediate
JUnit reports, or after completion if they only write a final report.
Live observations do not mark a task as passed; final retained evidence decides
its outcome. The Time column shows seconds (s), or milliseconds (ms) below one
second, inside a bar. Its fill shows each item's share of measured sibling time.
At every expanded level the measured children total 100%, independently of their
parent's share. For example, commonUtils at 10s is 10% of 100s of Android tasks;
its children divide their own measured total. If other tasks bring Android to
200s, commonUtils becomes 5% while its children still total 100%. Unmeasured
children join that calculation as timing arrives. These are measured time shares,
not estimates of completion. Parallel work can overlap, so
reported work time differs from elapsed run time; unmeasured items show no bar.
Reused tasks are labelled Reused. Their task, folder, file and test times show a
dash with no bar and do not contribute to current timing shares. Tooltips retain
previous-run durations where available; cached outcomes remain inspectable.
Running, passed, failed and awaiting-approval cards use blue, green, red and amber
backgrounds in both light and dark themes; blocked and skipped cards are muted.
Live palette changes refresh manager-local styles together while preserving view
selection and zoom; buttons continue following the active application accent.

Uploads, delivery and hosted test launches identify their approval boundary.
Start authorizes selected Firebase, TestFlight and GitHub actions in fresh plans.
Delivery runs after its required checks and package preparation pass; GitHub
hosted test launches run at their dependency point. Other external
steps pause for separate approval and their dependent work waits too. Legacy whole-plan external operations
still ask for explicit confirmation before Start. Changing any selection or saved
setting requires a fresh plan review.

## Run and results

Android and iOS validation can proceed independently within the worker limit.
When a step needs a resource already in use, its card shows Waiting and names
the shared resource. Open the card and select the subtask to see the resource
capacity and other steps that request it. A resource wait differs from a failed
prerequisite; unrelated platform work can continue. Platform-specific sequences,
such as cleaning up one iOS simulator before starting the next, still apply.
Previously saved plans retain their original order; prepare a new plan after
updating the manager and project adapter to use the new scheduling policy.

The main workflow cards retain the captured Source, platform, preparation and
destination groups during execution and while viewing retained runs. Selecting a
card filters the persistent task list without navigating into another map.
Select a task for Details, Command and Plan, just as in Review. The additional
Results tab contains reported test totals, individual Tests, Timing, Output and
relevant Files and deliveries. The run heading shows finished steps and current
states; each card updates with its measured progress.

Shared preparation stays in the chosen package cards, with shared task references
where needed. Other resolved subtasks exposes work the project did not map to a
chosen card. Prerequisite buttons select the relevant task without starting work,
including across card boundaries. View blocking step selects the recorded failed
prerequisite. View problems finds the failing step or reported test. Unknown
outcomes take priority. Source displays its captured identity without inventing
executable steps when capture already happened during planning.

All tasks clears the card filter. Maps support pan, zoom, Tab and Space.
Best fit adapts the overview to the available panel: it tries horizontal and
vertical arrangements and modest card widths so labels can wrap before shrinking
the whole map. Horizontal and Vertical keep your chosen direction. Manual zoom
preserves the arrangement while resizing; Fit resumes automatic sizing.
The Source, Testing and Delivery backgrounds fill the overview's available
height while cards retain bounded sizes within each section.

Live updates preserve selection, pan and zoom, and the text selection and scroll in
error details. Live test events are collected into short display batches so input
and resizing can run between updates. Hidden Review maps refresh when opened
rather than redrawing for every running test.

Card text and colored edges identify running, passed, failed and approval states.
When the project records each device's execution steps, a device card summarizes
only that device's connection and installation. A completed install remains green
while another device waits to reconnect. Approval badges follow the captured
actions' approval policy. Older plans without per-device mappings show shared
destination work; preparing a new plan with a project adapter that supplies those
mappings is required for separate device status.
Execution cards reserve space for live status and progress so their size and map
position stay stable as tests change. Long activity labels end with an ellipsis;
hover for the full text or inspect the test tree and Details.
A failed prerequisite immediately mutes affected pending descendants and explains
why they will not run. This is a display prediction, not a new execution result;
the executor later records skipped steps. Muted cards remain selectable. Cleanup
steps declared to run after failure remain eligible, and unrelated branches stay
independent.

Summary shows reported test counts and guidance for the next action. Timing
lists measured tests slowest first, with total, average and median durations.
Missing durations are excluded from statistics; summed test time differs from
active run time because parallel work can overlap.

The graph includes every execution step belonging to its card from the start.
Running cards and their inspector share the same elapsed clock; completed steps
retain measured durations. Never-started steps show Not started rather than a
synthetic zero duration. Main cards label summed durations as Total step time
(may overlap); this is distinct from the run's active time and individual test
time. Select a step's Details for
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
execution. Output is scoped to the selected step or all steps in the open card;
unassigned runner messages appear when viewing all steps in that card. Saved runs can preview each step’s retained log
within its own result directory. Console text is never treated as proof that a case passed.

Cancel operation requests cancellation and owned cleanup. Closing the application
during active work offers the same cancellation path. Open results and logs opens
the project-owned evidence folder.

## Continue delivery in one session

An integrated project plan can test, build and prepare delivery in one run.
Firebase, TestFlight and GitHub actions authorized by Start proceed without another
prompt. Older saved runs retain their approval requirements. When a phase
requires separate approval, it pauses for review. Select
Review and continue delivery to see selectable cards with exact destinations,
captured recipients and prepared file identities. The cards use the workflow's
approval badges and selected outlines. Package/version/build fields appear when
present in retained JSON evidence; file names and checksum fingerprints remain
visible. Expand Technical evidence for original settings, full paths, checksums
and JSON. Missing declarations are shown explicitly rather than inferred.
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
Logistics local builds, device delivery, Firebase and TestFlight can use captured
current files. Full release-acceptance gates still apply to Release packages.
GitHub-hosted execution requires committed source.
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
Each device still has its own reviewed installation. Release packaging uses the
captured source, the existing release signing setup and full release gates.

The overview explains source requirements for selected destinations. Current files
can be used for local tests, Debug and Release device packages, Firebase and
TestFlight. GitHub-hosted execution requires committed source; GitHub source
releases also require a clean checkout matching that commit. Latest commit
excludes edits without committing them. Selecting a source never commits or pushes it.
