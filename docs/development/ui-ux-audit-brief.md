# Build Deployment Manager UI and UX audit brief

**Status: Balanced workspace approved and implemented; UI validation complete. Reviewed 3 November 2026.**

The recommended direction is a calmer native desktop workspace with a clear
sequence: choose intent, establish source, choose platforms and execution
locations, choose destinations, review captured facts, then start the eligible
work. Give editing and evidence more room, make the workflow map easier to read,
and use strong emphasis for the next action or the problem requiring attention.
Preserve the map and persistent inspector as the application's defining working
surface.

This brief covers the complete manager UI, including secondary dialogs and
failure/recovery states. The owner approved the Balanced workspace direction and
all six implementation slices. The findings below record the audit baseline;
the implementation record describes the resulting changes.

## Implementation record

| Slice | Implemented behavior | Validation |
| --- | --- | --- |
| Shared visual foundations | Scalable headings and application fonts, native accent actions, distinct focus, semantic status colors, wrapping actions and font-aware rows/cards | Palette/action contracts; offscreen and native enlarged-font checks |
| Shell and Choose work | Bounded project picker, separated History, one stage explanation, presets beside the form, balanced panes, grouped delivery/platform rows and full-width manual recipient entry | Intent, preset, recipient, repair, build-only and workspace contracts |
| Review | Visible captured source/hosts/destinations, compact full-value disclosure, more inspector space, adaptive task height and explicit evidence scope | Captured facts, plan immutability, prerequisite navigation, manual-pane and selection preservation |
| Progress and evidence | One Evidence selector, main views before technical views, one global attention summary with footer actions, saved-run identity, stable output selection/scroll | Scoped results, failures, unknown outcomes, approvals, history and retained-run fixtures |
| Supporting tools | Compact text preferences/preview; category settings heading; method-specific account inputs; clearer registration; staged machine setup; scoped storage actions and advanced adoption | Inert dialog captures, asynchronous settings/storage and explicit approval contracts; no real machine/device/provider operations |
| Native acceptance and guidance | Updated operator guide and current review reference; native Cocoa fixtures and captures, including 1024×700/1280×800 and enlarged text | Automated native Qt acceptance is separate from manual screen-reader, Windows/Linux desktop and operator-study acceptance, which remain unverified |

Automatic map layout preserves readable text and can require panning. Explicit
Fit still shows the complete workflow. Font changes resize existing card content
without rebuilding its identities. The preserved nested browser remains
unconnected in both Review and Progress.

Initial broad UI validation exposed timing failures while multiple native/render
checks were active and source was changing. The history-responsiveness fixture
now holds its worker with an event, proving timer delivery before release. Final
validation uses isolated interpreters and a fixed checkout for full manager and
consumer acceptance. Raw per-module logs and captures remain ignored evidence.

### Recorded UI acceptance

Per-module portable results cover **37 UI modules and 260 cases**, including
passing focused reruns of every initially failing/timed-out module. Native Cocoa
acceptance covers **75 cases in nine modules**. A further **17 native font and
docked-control cases** passed after consolidating font-change observation.
The offscreen workspace module then passed all 13 cases in 37.8 seconds; the
prior 240-second timeout exposed redundant per-heading application event filters,
which were removed in favor of the existing single font controller. No assertion
was weakened to accept partial completion.

Measured custom status text pairs and the active/inactive native primary palette
range from **6.11:1 upward** in the inspected light/dark configurations. This
records those pairs, not a universal native accessibility certification.
Representative offscreen and native captures verify forms, review/evidence,
secondary dialogs and enlarged text; raw evidence remains ignored.

The coordinated developer-validation chat owns the full manager and Logistics
compatibility runs in an isolated checkout with each project's real interpreter
and commonUtils pin. Their final result is separate from this UI acceptance.
Native Windows/Linux, manual screen-reader use and a new-operator study remain
unverified; no real delivery, provider, VM or device acceptance is claimed here.

## Approval decisions

The approved decisions are:

| Decision | Recommended direction | Consequence |
| --- | --- | --- |
| Workspace emphasis | Balanced editor and overview in Choose work; more evidence space in Review and Results | Replace the current map-heavy default proportions; preserve manual resizing |
| Navigation | Keep independent run tabs and the three workflow stages; separate History visually from the sequence | Remove the duplicate breadcrumb and distinguish workflow progress from saved-run browsing |
| Configuration | Keep Source, Platforms, Delivery and Options sections; flatten delivery's category/platform tab nesting | Destination choices become grouped rows with inline selected options |
| Overview | Keep the captured cards and dependency relationships; use content-sized cards and restrained section backgrounds | Avoid filling spare height with large empty cards or shrinking all labels to make everything fit |
| Evidence | Keep a persistent task list and inspector; replace nested Results/Plan tab rows with one evidence selector | Tests, timing, output and files gain usable vertical space and a clear scope |
| Emphasis | One filled next-action button per active surface; distinct selection, focus and status treatments | Reduce repeated alert/action chrome and large colored regions |
| Supporting tools | Use compact forms for accounts/preferences and task-based sections for machines/storage | Maintenance no longer competes visually with the run workflow |
| Delivery and recovery | Improve presentation using existing eligibility, verification and approval contracts | No change to what Start authorizes, what needs approval, or what can be retried |

Approval of this brief authorizes a subsequent UI implementation pass in this
repository. It does not authorize device/VM operations, provider actions, pushes,
dispatches or publication. The nested workflow-card browser remains dormant;
approval of this brief is **not** a request to reconnect it.

## Audit scope and evidence

The audit began with the working checkout at `039f9ac`, including unrelated
uncommitted adapter/documentation work. Other work advanced the checkout during
the audit, including extraction of delivery controls into
`configuration_delivery_ui.py`; the visible tab structure remained the same.
Findings use inspected source and rendered Qt fixtures, not the earlier briefs
as a description of current behavior.

The audit rendered the actual manager widgets with temporary synthetic projects,
run facts and protected-reference placeholders. It exercised section selection,
card selection, inspector views, failure presentation, history filtering surfaces,
multiple run tabs and secondary dialogs. Screens were inspected at 1280×800 and
1024×700 where specified by the fixture; dialogs also used their existing default
sizes. A larger-font probe and a manually supplied dark palette were captured.
These are offscreen layout inspections, not native platform, screen-reader,
real-provider or operator-study acceptance. The palette probe does not establish
correct operating-system theme switching. No build, delivery, device discovery,
VM operation or real project planner ran.

Raw captures, fixture code and logs belong under ignored `test-results/`, as
required by the repository. The UI's visible content is adapter-dependent: this
audit establishes layout findings and design hypotheses, not the completeness of
any particular project's release inventory. Synthetic test cases include the
normal suite/class/status fields expected by the UI.

### Coverage inventory

| Surface | Inspection | Main question |
| --- | --- | --- |
| Empty application and project setup notice | Rendered + source | Is the first action obvious without duplicated instructions? |
| Run tabs, project picker, More and Help | Rendered + source | Is scope clear across projects and simultaneous runs? |
| Add project, moved checkout and registration removal | Dialog rendered; routing read | Can users distinguish registration from changing project files? |
| Goals, presets and Project operation | Rendered + source | Is intent distinct from saved choices and execution? |
| Source, platform/host, delivery and Options sections | Rendered + source | Does the form follow decision order and provide enough room? |
| Recipients, notes and shared run fields | Rendered + source | Are inputs attached to the destination they affect? |
| Proposed map, requirement repairs and display controls | Rendered + source | Are dependencies readable and missing choices easy to repair? |
| Review cards, captured choices, tasks and inspector | Rendered + source | Can the operator explain what Start will do? |
| Plan summary, dependency table, command and JSON | Rendered + source | Can detailed evidence be reached without taking over the default layout? |
| Run overview, attention area and error details | Rendered synthetic failures + source | Can users find the cause and affected destinations? |
| Results summary, Details, Tests, Timing, Output, Files and deliveries | Rendered + source | Is the evidence readable, discoverable and correctly scoped? |
| History and opening a saved run | Rendered inventory; routing read | Is inspection clearly separate from continuation? |
| Delivery approval and retained verification | Approval rendered; verification/recovery read | Are exact effects and selections reviewable before consent? |
| Project settings and loading/save/error states | Ready/no-match rendered; async states read | Can users find, edit and recover without losing changes? |
| App settings | Rendered + source | Does this stay focused on application preferences? |
| Connected accounts | Rendered + source | Does each reference kind ask for the appropriate input? |
| Dedicated test machines | Rendered idle + source | Is maintenance organized around the machine's lifecycle? |
| Storage outputs, retained workflows, adoption and confirmations | Tabs rendered; mutations/confirmations read | Are deletion scope and protected state understandable? |
| Optional project command panel | Rendered with inert policy + source | Are target, operation and result hierarchy clear? |
| Documentation host, file choosers, generic confirmations and detached windows | Integration/source review | Are native conventions and ownership preserved? |
| Dormant nested browser and supporting summary/map views | Source review only | Preserve deliberately; do not count hidden widgets as visible clutter |

### What already works

Keep independent run tabs, checkout-specific settings, asynchronous preparation
and settings I/O, the persistent footer, explicit reviewed Start, destination
approvals, actionable requirement repairs and the retained-run model. Card
selection already filters the side pane without replacing the overview. Failures
already expose full evidence, and unrelated updates preserve selection and text
where supported. These are foundations to refine, not reasons for another
navigation system or execution-model rewrite.

## Principal findings and priorities

Priority 1 affects task comprehension, action scope or access to essential inputs.
Priority 2 improves consistency and efficiency. Priority 3 is finishing work.
These are design priorities, not measured incident severity.

| ID | Priority | Current observation | Recommended outcome |
| --- | --- | --- | --- |
| UX01 | 1 | At laptop width the configuration pane loses section/category labels to tab scrolling; the recipient ID input becomes extremely narrow | Reserve form width first and eliminate nested delivery tab rows |
| UX02 | 1 | Review/Results split the right column vertically, leaving a small detail viewport below a tall, sometimes nearly empty task tree | Allocate height by useful content; let evidence dominate a one-task selection |
| UX03 | 1 | Results adds a second tab row inside the inspector; Plan has its own nested tabs | Use one visible evidence selector with explicit scope |
| UX04 | 1 | Captured source/run facts are principally behind a disclosure; the summary and Start explanation are separated | Keep a compact source/hosts/destinations/authorization summary visible before Start |
| UX05 | 1 | Failure presentation repeats attention, error-navigation and footer actions | One global attention summary, one primary recovery action and local cause details |
| UX06 | 1 | Map fitting makes small text in dense/narrow layouts; tall review cards can contain substantial empty space | Preserve readable card content, pan when necessary and keep alternate task access obvious |
| UX07 | 1 | Selection, running status, platform section colors and action accent all contribute emphasis | Separate selection/focus/action/status semantics and reduce decorative color |
| UX08 | 2 | Choose work repeats the workflow sequence below the stage navigation; presets span the full workspace | Remove duplicate navigation and place presets beside the choices they load |
| UX09 | 2 | Source appears both as configuration section and delivery category; Test is awkward for build-only intent | Use Platforms and Source releases/Release as unambiguous labels |
| UX10 | 2 | Forms mix explicit labels, placeholders, broad tooltips and fixed-height inputs | Standardize labels, supporting text, validation, spacing and text scaling |
| UX11 | 2 | Accounts exposes provider/reference implementation terms and a credential-file action when inapplicable | Render a short form for the selected login/reference method |
| UX12 | 2 | Machines presents refresh, creation, power, permissions and two installation methods together | Present status first, the relevant next task second and advanced maintenance last |
| UX13 | 2 | Storage places explanatory paragraphs before inventory and destructive actions in a peer row | Lead with scope/space/protection; separate destructive actions and name their selection |
| UX14 | 2 | App settings mixes appearance, project settings links and a multi-step workflow tutorial | Make preferences compact; keep workflow guidance in Help/onboarding |
| UX15 | 3 | Typography uses a mixture of point/pixel sizes and repeated local style rules | Apply shared scalable type, spacing and semantic color tokens |

## Reading order and application structure

### Window and run scope

Use the following vertical order:

1. **Run tabs:** project name plus an identifiable run label and concise state.
2. **Active-run context bar:** project picker, checkout identity on demand,
   Project settings, More and Help.
3. **Workflow navigation:** Choose work → Review plan → Progress & results.
   Place History at the trailing end with visible separation.
4. **Stage title and one sentence of current state.**
5. **Stage workspace**, including its local tools.
6. **Persistent footer:** backward/secondary action, short action-scope or blocker
   message, primary next action.

Keep project controls inside each run, including detached runs. Do not create a
shared toolbar whose target silently changes. Keep the three stage labels stable;
availability and completion should be shown by state, not renamed tabs. History
is browsing, not step four of a build.

The project picker currently stretches across almost the entire context bar.
Give it a useful bounded width and give the adjacent space a purpose only when
context needs it. A short checkout suffix can disambiguate worktrees; the full
path remains selectable/copyable on demand. Do not require hover to distinguish
two otherwise identical project names.

Use a small run-state icon plus text in tabs when available: Draft, Running,
Needs approval, Failed or Complete. Avoid full tab background colors and animated
timers in every tab. A user can detach through an explicit menu as well as drag.
Keep close protection for active work and the last-tab ownership rule.

Group More into Project registration, Project tools, and Application preferences.
Use section names or clear separators without adding another toolbar. Settings,
accounts, machines and storage must state their actual scope; machines currently
belong to the manager checkout even when opened from a project run.

### First run and project registration

The empty screen currently repeats adding a project in the setup notice and body.
Use one concise welcome area aligned to the main content column: what the app
does, Add project, and a short explanation that adding allows the checkout's
tools to prepare plans. Keep a documentation link secondary.

In Add project, order folder → discovered project/readiness → optional
registration name → Add. Show the discovered name/platforms as labeled facts,
and distinguish a missing environment from an invalid project folder. Registration
name should read as optional and explain worktree naming outside its placeholder.
Expose descriptor JSON under a disclosure whose label changes with its state.
Keep the footer anchored and avoid a large blank body for a short form.

Locate moved checkout should name the registration and original location before
the replacement chooser. Remove registration should say that it removes this
entry, with its existing actual data-retention consequences stated precisely.
Do not imply deletion of the checkout. Preserve the current trust/registration
contract; no new generic approval screen is proposed.

## Choose work

### Goals and presets

Keep Run checks, Build only and Prepare and deliver as mutually exclusive intent
choices. Give the selected choice a subtle fill plus clear selected marker.
Reserve the filled action style for the footer. Project operation remains a
lower-emphasis explicit route, with the selected state apparent when used.

Place presets on the configuration side below intent or beside the local
configuration heading. Use a labeled Preset picker with Save/Delete in its small
menu. Modified is a quiet state next to the name. Distinguish user-saved presets
from project-declared Suggested workflows in Project operation; they have
different sources and should not appear to be competing versions of one control.
Loading choices must continue to invalidate review without executing anything.

### Space allocation

The existing configuration defaults favor the overview approximately 3:1 at wide
sizes. In the inspected laptop layouts the editor stays around its 350-unit
minimum, producing horizontal tab overflow and compressed inputs.

Start with **42% configuration / 58% overview** at 1280×800, using a form minimum
around 420–460 logical units at the normal font. These are prototype values to
tune against real labels, not fixed cross-platform pixel requirements. At
1024×700, allocate approximately 44% to editing and simplify the map toolbar
before reducing input width. Keep splitter adjustment available and remember
user sizes per stage/window where appropriate. Do not reset them on live updates.

The tradeoff is less map area. Address it through card density, meaningful zoom
and pan, rather than shrinking form text. The operator spends this stage making
choices. A map-heavy balance remains possible by dragging the splitter; another
permanent layout preference is unnecessary initially.

### Section order and forms

Use **Source → Platforms → Delivery → Options** as the visible section order.
This follows the source/host/destination dependencies without forcing a wizard.
Card selection should continue to open the matching section and exact destination.
Keep a section's active state and selected counts visible without color alone.

**Source:** show Build from first, followed by the revision field only when
needed. Keep Current files includes edits and Latest commit excludes edits in
visible supporting text, not only a long dropdown label. Show a custom revision
as entered until resolved; do not make a draft branch/tag look like an immutable
captured commit. Put committed-source requirements beside the affected choice.
Never change source mode automatically when a host changes.

**Platforms:** keep platform selection and execution location on the same row.
Use a readable label such as Run on rather than backend jargon. Disable a host
control only when its platform is unselected or the actual capability forbids
it, and provide a visible reason when needed. Row height must follow font and
control size rather than a fixed 38-unit assumption. Use a simple aligned list
when native embedded table controls cannot scale gracefully. Keep project-required
checks explained below the platform rows. Workflow-wide options, such as reuse
of verified results when declared, appear once under the checks they affect.

**Delivery:** replace category tabs plus Android/iOS subtabs with a single
grouped destination list. Use adapter-declared categories as quiet section
headings, then platform labels and destination rows. Selected rows expand their
notes, recipients and overrides directly beneath the checkbox. For long lists,
allow category disclosure while retaining a visible selected-count summary.
Keep empty categories out of the main scanning path; declared unavailable
destinations retain a truthful explanation. Do not silently choose a platform
or recipient to resolve a conflict.

Put the destination's human name first, provider/platform second, and exact
identity where the project supplies it. Notes and recipients belong to that
destination. Shared fields appear once with a statement of which choices they
affect. Label count units: destinations and devices are different quantities.
Use Source releases rather than Source for a release destination category.

**Recipients:** give saved devices a readable full-width checkable list, a
selected count, and selectable identity details. Label Reload as Reload saved
devices and explain that this does not scan devices. Move manual ID entry into
an Add device by ID disclosure or full-width row; its current tiny inline input
cannot show a useful serial. Show saved metadata as unverified until existing
execution checks establish connectivity. Preserve selected-but-unavailable
identities explicitly, and keep all existing validation and recipient limits.

**Options:** place focused test pattern with test scope, build number with build
overrides, and release identifier with release settings. Show only controls
applicable to the current declared operation. Keep Automatic explicit; a blank
field is not enough to explain naming policy. A build-only goal must not be
presented as if it necessarily runs validation.

**Project operation:** suggested workflow first, then platform → operation →
execution location → suite → operation inputs. A Modified label and Restore
suggested workflow stay near the suggestion. An unsupported selection needs a
local explanation and explicit correction, not a silent fallback.

### Requirements and preparation

Keep the existing repair behavior that navigates without changing values. Replace
multiple prominent amber buttons with a compact requirements list: specific
problem, affected destination/platform, and a neutral Fix control. Show the count
and first actionable issue near the footer. Use amber on the warning marker or
short message, not every dependent card and every repair button simultaneously.

Preparation state should read Preparing plan, with the current phase and a
neutral Cancel preparation action. Preserve the choices and show preparation
failure beside Next, with the short reason before expandable redacted technical
details. When Next can launch preparation that may discover more requirements,
its copy must not claim the plan is already verified. Preserve current enablement
and validation semantics unless a separately tested behavior change is approved.

## Workflow overview and interaction

Keep Source, Testing, preparation and delivery relationships legible, using the
project's declared graph. Grouping and screen position must never imply a new
execution sequence or dependency. Keep shared executable identity and unmapped
work reachable through the existing mechanisms.

Use content-sized cards with consistent internal padding, a clear title and
one or two supporting lines. Review cards should not stretch into large blank
rectangles solely to fill section height. A card can grow for an actual warning
or approval requirement. Shorten repeated text such as project resolves build
steps during Review once the stage itself already explains the distinction.

Section backgrounds should be neutral or very lightly tinted. The current large
blue/green/amber regions compete with execution state and dominate empty space.
Keep section headings and geometry tracking; reduce their decoration. Retain
platform/provider icons as identity cues without turning every icon into a new
color system.

Keep the card title and state readable at normal zoom. Fit is an overview command;
if all cards cannot fit at a readable size, provide pan/zoom and retain the full
task list as an equivalent route to every task. Do not make auto-fit the only
usable reading mode. Keep a stable default orientation; Best fit and Follow mouse
belong under View options, with Fit and compact zoom controls visible. Preserve
Follow mouse's existing off-by-default behavior and preference.

Use one local map toolbar, not two stacked rows of map commands plus generic
navigation. Keep All tasks adjacent to the task-list scope, while a neutral
clear-selection route remains easy to find. Cards must look selectable without
suggesting they open another screen: use a selected outline and explicit side-pane
scope text. Reconsider the chevron if it suggests drilldown; do not reconnect
the nested browser to justify the icon.

Keep prerequisite tracing for pointer and keyboard. Dimming unrelated work must
not make essential blocked/skipped labels unreadable. Hover may highlight
relationships but cannot be necessary to discover status, inspect evidence or
reach another task. Keep selection stable while facts update; no automatic
zooming, scrolling, card rearrangement or focus stealing on timer ticks.

## Review plan

### Information order

Show these before the main workspace:

1. Ready to start, or the concrete reason this review is unavailable.
2. Captured source: mode, resolved identity and edits/snapshot state when known.
3. Selected platforms with execution locations.
4. Destinations and recipients, with prepared/approval expectations derived from
   the actual plan.
5. A short Starts now / Requires later approval statement.

Use a compact, wrapping summary band rather than four large dashboard tiles.
Keep full hashes, long notes, provenance and redacted plan details expandable.
The default collapsed summary must still expose enough to detect the wrong
source, host or destination. Copyable identifiers need an explicit detail path,
not only hover.

### Workspace proportions

Retain **overview left / persistent task list and inspector right**. Start near
45% overview / 55% evidence at 1280×800; compare against the current approximately
3:2 allocation. Use a visible splitter with a broad enough hit area. On the right,
the task list should take roughly a third of the available height for ordinary
plans and shrink for a one-task selection. The inspector receives the remainder.
Keep manual vertical resizing and preserve it across Start.

For a dense list, task filtering must retain a visible scope label and an All
tasks reset. For one task, avoid reserving half the column for a single row.
Show task title, state and measured duration, with full identity on demand. State
width should be font/content-aware; a fixed narrow column truncates the very
reason a blocked row matters. Keep row identity and expansion stable.

Details should begin with purpose and where the task runs, then state/reason,
outputs/destination, prerequisites and further notes. Suppress empty fact labels.
Do not force every fact into a tall label-over-value pair when two short fields
can share a row. Long values wrap; exact paths remain copyable. Show unmeasured
time as Not started or an explained dash, never an invented estimate.

### Start action

Keep Back to choices on the leading side and one primary Start on the trailing
side. Choose its short label from actual effects: Start checks, Start build or
Start preparation, with scope text immediately adjacent. Mixed plans need a
truthful generic label and explicit scope sentence rather than a guessed
project-specific action. A disabled action needs its reason in the same region.

The actual plan and approval gates decide what starts. A dispatch is an external
action even when it launches tests; legacy whole-plan confirmation remains when
required. Improve copy without changing these contracts. Captured values must
remain independent of later edits in another run tab.

## Progress and results

### Global status and attention

Use one stage heading, a concise overall state line and measured progress facts.
Clearly separate steps finished from tests passed; failed and skipped tasks are
finished work, not successes. Keep elapsed time and reported-case totals distinct.
Show unavailable counts as unavailable and provisional results as provisional.

Use a single global attention region. Its priority is unknown external outcome,
actionable failure, eligible approval, then ordinary waiting information. If a
failure and an independent eligible delivery coexist, show both, with one primary
action appropriate to the current situation and a secondary route to the other.
Changing selection must not hide global attention.

Remove duplicate global View problems/View error details controls. The global
action opens the relevant cause; the selected task retains local traceback/output
and View blocking step. A blocked destination should name its failing prerequisite
and provide the existing cross-card navigation. Avoid portraying every downstream
blocked card as an independent error.

While running, keep Cancel visible and neutral. Cancelling becomes Stopping until
cleanup actually finishes. Keep resource waits, reconnect waits, prerequisite
blocks, approval waits and queued work distinct in text. Activity counts remain
useful navigation, but use quiet compact controls instead of another dashboard.
Never invent an ETA from completed-step counts.

### Evidence navigation and scope

Replace Details / Command / Plan / Results plus nested tab bars with a single
evidence navigation control. At sufficient width it can be a compact tab row;
otherwise use a labeled native selector. Recommended main choices are Details,
Tests, Timing, Output, Files and deliveries. Put Command, complete plan summary,
Dependencies and redacted JSON under Technical details in that same navigation
model, not another row inside an already small pane.

Above the evidence, keep **Scope: whole workflow / selected card / selected task**
visible. Do not confuse switching an evidence view with changing its scope.
Whole-run outcome stays in the global header; selected evidence is local. Finding
problems can deliberately widen scope, but must say it is showing problems across
the run and provide a route back. Keep the same selection between Review and Run.

| Evidence view | Proposed reading order and layout |
| --- | --- |
| Whole-run summary | Outcome and next action → platform/destination outcomes → reported-case totals → relevant evidence links. Use compact totals, avoiding oversized 24pt zero cards in a short inspector |
| Selected Details | Task identity and state → concise error/reason if present → purpose/host/time → outputs and prerequisites → expandable full technical evidence |
| Tests | Scope and final/provisional counts → search and status filter → readable case list → resizable selected-case message. Make Show failed tests a filter/navigation action, not another global primary button |
| Timing | Scope and timing definition → slowest measurable items → duration and share. Distinguish summed case durations from wall time and exclude missing duration from averages |
| Output | Scope label and retained/live indicator → selectable monospaced output. Preserve reading position when the user scrolls away from the end; expose follow-live state if that behavior is added |
| Files and deliveries | Destination identity and recorded outcome → producing task/prepared file → local path/details. Keep provider accepted, device install outcome and local file retention separate |
| Command | Exact redacted command, working directory, declared effect, timeout and resource settings; readable technical formatting without losing copy/select |
| Complete plan and dependencies | All declared tasks and dependency relationships, independent of the card filter; selected prerequisite can reveal its task without changing the plan |
| Redacted JSON | Clearly technical and read-only, with complete content reachable; never use it as the main run explanation |

Do not add local approve/retry buttons to every card. Existing retained
verification and continuation sessions remain the authority. Retry uncertain
device install must remain explicitly scoped and cannot become a generic Retry
failed run action.

### Completion and retained runs

Keep the current view on completion. Replace generic success with actual outcomes
such as Checks passed; delivery awaiting approval or 1 of 2 destinations delivered
when supported by facts. A retained run needs a persistent Saved run indication,
its original source and date, and its original engine identity on demand. Viewing
must never enable Start for that historical plan.

Continue/review actions should state which retained run they affect. Verification
progress belongs above that run's evidence with a clear cancellation route. If
verification fails, keep the evidence and show the precise next step. A manager
version change should compare previous/current versions as labeled fields with
technical identity expandable, instead of leading with a JSON wall. Preserve
existing decisions, stale-review rejection and unknown-outcome blocking.

## History

Lead with History, search and status filter, then the list. Keep Started,
Operation, Outcome, Active time and Next step, with widths driven by useful
content. Dates should remain locally understandable; exact timestamp/time zone
and run identity stay available in details. Do not add more identity columns
until the operator needs them.

Keep View selected run as the primary action after selection, with wording that
the result opens in another run tab. Refresh is secondary and should preserve
selection and scroll. Continue a saved run currently opens a file chooser; label
that route Open saved result file or similarly make its file-based behavior clear.
Opening a record should precede any consequential continuation approval.

Distinguish No runs yet from No matching runs, and provide a way to clear filters.
Keep unreadable records, cancelled runs and retired workflows truthful. The
current Completed filter means passed, while Needs attention means non-passed;
consider labeling the former Successful and documenting/filtering the latter
more precisely so ordinary recorded-running/queued states do not imply the same
urgency as unknown external outcomes. Preserve original outcomes in the list.

## Delivery approval

The existing unchecked per-action cards and counted approval button are good.
Keep them. Organize each card as action/destination → source/build identity →
recipients/notes → prepared files and verification → authorization control. Make
the action title part of its checkbox label so the selected effect is explicit
without reading a generic Authorize label and then another heading.

Use amber for the pending-approval state marker, an accent outline for selection,
and a separate visible keyboard focus indicator. Reduce repeated Approval required
badges if every card in the dialog shares that state. Keep the exact destination
identity readable and long notes expandable without separating them from the
destination. File hash/path details must be copyable on demand rather than
available only through tooltip.

At the bottom, show the selected action count and a precise action label when
possible, such as Approve 2 deliveries or Approve GitHub launch. Mixed effects
can keep Approve selected actions with a concise scope summary. Cancel stays the
safe keyboard default; Return must not bypass explicit per-action selection.
Cancelling preserves pending approval. Selecting one action must not silently
authorize its peers. Verification, artifact hashes and exact-source checks stay
in the existing continuation flow.

## Project settings

Keep the category list and searchable form. It is a stronger pattern than moving
settings into the already dense run UI. Add a clear category heading above its
fields, keep input widths useful, align labels consistently, and give fields
enough vertical separation to associate descriptions with their own input.

Order categories using adapter-declared navigation where available. Do not invent
manager-owned release policy or rearrange project-specific fields based on guessed
names. Within a generic fallback, preserve declared order. Separate ordinary
fields from advanced provenance; Show value sources stays available without
making the default form verbose.

Keep scope visible as project name plus checkout, with the full path available
without taking multiple header lines unnecessarily. Search should show matching
categories and a clear no-match state. Preserve edits and category context when
search changes. Label environment/read-only values explicitly; disabled controls
alone do not explain why a value cannot be edited.

Use a stable bottom status for Unsaved changes/Saving/Save failed, with the failing
field marked locally when the adapter provides that mapping. Do not guess field
ownership from an arbitrary error string. Keep retry and cancel during loading,
locked writes while saving, preserved input after save failure and discard
confirmation on dirty close. Successful save still invalidates relevant reviews
across tabs. Avoid adding success popups for ordinary saves.

Use labeled tool/directory/reference pickers consistently. Credential references
remain references, and existing protected-location checks remain unchanged.
Large multiline settings should expand with their content or provide a deliberate
resizable area; fixed 110-unit fields should not clip enlarged text.

## Application preferences and Help

App settings currently dedicates a relatively large dialog to text size, a
configuration-folder action and workflow guidance. Make it a compact Preferences
form with Text size, a representative preview and System default/Reset behavior.
Validate supported sizes; do not silently accept unusably tiny body text. Any
change to the stored supported range needs a compatibility decision and tests.

Keep Open configuration folder as a secondary advanced utility. Move the multi-step
workflow tutorial into Help or first-run guidance. If a project-settings shortcut
stays, identify the checkout and avoid opening a second settings modal with
ambiguous save/invalidation scope. Help remains directly reachable from each
window. Preserve the existing local documentation host and its user/developer
landing structure; the audit does not propose a new documentation system.

## Connected accounts

Use account selection → provider → login/reference method → method-specific
inputs → reference status → Save. Describe methods in ordinary language while
preserving the stored kind values. For example, Environment variable name asks
for a variable name; Protected file asks for a path plus Choose file; Existing
CLI login explains the reference it uses. Do not show an inapplicable disabled
credential-file button across all providers.

Give the dialog enough width for provider labels and a useful reference. A single
generic placeholder currently has to explain several incompatible input types.
Make Reference name a reusable local name with an example; show project binding
scope explicitly when Save binds it. Reference exists, authenticated account,
provider read access and delivery/signing permission are different facts and
must have different status copy. Retain existing check behavior without claiming
it verifies provider permission. Keep errors near the form and preserve input.

## Dedicated test machines

The idle dialog currently exposes six peer actions, two permission controls, media
and digest fields, installer attach, two initialization routes and a log. Reorder
it around the selected owned machine:

1. Operating system and manager-checkout ownership.
2. Machine identity, power state, setup/readiness state and last observed status.
3. The relevant next task, such as Refresh status, Create or recover, Finish OS
   setup or Check readiness, derived from actual recorded facts.
4. Secondary power/console controls in a compact maintenance area.
5. Setup media and installation method disclosure, showing only applicable
   Linux/Windows controls.
6. Advanced guest-command/filesystem permissions with their existing explicit
   confirmations, then expandable progress/logs.

Keep Refresh available as a neutral utility after initial status is known. Avoid
coloring it as the universal primary action. A destructive/permission-changing
operation must never look like a routine refresh. Show action progress in the
status area and explain why closing is temporarily unavailable. Do not introduce
background probing, VM adoption or automatic power operations as part of visual
cleanup. Keep held/personal machines outside this workflow.

## Storage and retained workflows

Show project/scope first, then total shown, protected and eligible storage as
compact inline facts, then category filter and inventory. Shorten the introductory
paragraph and put detailed protection rules in contextual help. Keep protection
reasons visible in rows; protected entries can remain inspectable even when
ineligible for deletion, provided the deletion contract remains enforced.

Move Refresh to the inventory toolbar. Keep Delete selected distinct from
Delete all unprotected, with the latter in a clearly separated bulk-action area.
When filtered, name the category in the bulk action or confirmation; the current
word all relies on a separate status sentence to explain its scope. Show selected
count and known size before confirmation, with unknown size labeled unavailable.
Never count parent and child allocations twice.

Keep retained workflows in their own tab with a short explanation of retirement,
holds and continuation consequences. Retire selected needs a visible selected
count and safe default confirmation. Logs, receipts and unknown external outcomes
must retain their existing treatment. A successful retirement is not proof a
provider outcome has been reconciled.

Move adoption actions to an Advanced ownership menu/disclosure. Name the exact
folder/simulator and ownership consequences in the existing confirmation. Never
make adoption look like ordinary browsing. For deletion/retirement results, prefer
a persistent completion summary with expandable skipped reasons over repeated
informational popups where practical. Preserve worker lifecycle and protection
rechecks; this is presentation work, not retention-policy change.

## Optional project command controls

Keep this optional panel subordinate to its project operation rather than making
it another global run mode. Order device/inventory state → exact selected target
→ available action → progress/result → logs. Distinguish refresh from install or
other effectful commands. All available devices must be prominent when selected;
it cannot look like an innocuous single-device default.

Action labels and effects remain policy-supplied. Do not infer dangerous actions
from command strings or invent a universal deploy policy. Use the manager's
shared spacing and button treatment while keeping existing interactive confirmations,
target retention, bounded output and process ownership. Missing/unavailable
targets need a visible explanation; they must not be silently replaced.

## Visual system

### Emphasis and color

| Meaning | Proposed treatment | Avoid |
| --- | --- | --- |
| Main next action | One filled button using the active native accent with contrasting text | Several filled actions competing in the footer/banner |
| Selected control/card | Subtle selected surface, accent outline/marker and persistent text state | Making selection indistinguishable from running or successful |
| Keyboard focus | Distinct focus ring visible over selection and status fills | Reusing only the selected border or losing focus in a filled button |
| Running | Compact activity indicator and Running label; optional restrained status tint | Saturating every active region blue |
| Passed | Success icon/text, with a light local status treatment | A large green background implying delivery success from check success |
| Failed | Error icon and concise reason, with a local error treatment | Treating every downstream blocked task as a separate red failure |
| Needs approval/requirement | Amber marker and explicit state/reason | Using amber for all Delivery section structure |
| Unknown external outcome | Strong attention label and reconciliation action | Presenting it as a routine retryable test failure |
| Queued/blocked/skipped | Neutral state text with distinct wording/icons | Muting essential evidence until it resembles a disabled control |

Centralize semantic colors and palette adaptation rather than adding another
set of per-widget literals. Current card states already have light/dark palettes;
preserve their truthful distinctions while testing the complete surrounding
surface. Sample actual foreground/background pairs, including hover, focus,
selection, disabled and dimmed graph states. A synthetic palette screenshot is
not evidence of compliant contrast.

### Spacing and typography

Use a shared spacing scale, starting with 4/8/12/16/24 logical units: 4 between
label and closely related helper, 8 inside a field group, 12–16 between ordinary
rows, and 24 between major sections. Use alignment and whitespace before adding
another border. Keep native control metrics and increase minimums with the font.

Use the application/system body font as the base. Derive one stage title,
section heading, body and secondary-text style from it; replace unrelated fixed
18px, 18pt and 24pt declarations with scalable roles. Avoid making every row bold.
Use monospaced text for commands, logs and hashes only. Align durations/counts
consistently and use tabular figures where available. Essential text must not
become small simply because the graph is dense.

Forms should use persistent labels, with placeholders reserved for examples.
Associate helper/error copy directly with the input. Use sentence case consistently,
ellipses for actions opening another choice/dialog, and explicit verbs for effects.
Avoid instructional paragraphs repeated in headings, tooltips and footer together.

## Adaptation and accessibility acceptance

Treat WCAG as useful measurable design criteria for this native Qt application,
not a claim that a web checklist establishes desktop accessibility. Adopt normal
text contrast of at least 4.5:1, large text 3:1, and relevant non-text state/focus
contrast of at least 3:1. Use clearly visible keyboard focus; the stronger
two-pixel-area focus target is a design goal rather than a claim it is an AA
requirement. Target-size guidance uses CSS units on the web; translate to native
logical-unit hit areas and test actual pointer usability rather than equating
the units mechanically. [Contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html),
[focus appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html),
and [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

| Condition | Required behavior after implementation |
| --- | --- |
| 1440×900 and wider | Readable overview plus generous editor/evidence; no artificial stretching of cards |
| 1280×800 | All primary controls and footer visible; ordinary form labels and evidence navigation fit |
| 1024×700 | Simplified local toolbars; useful form width; no horizontal page scrolling to reach a primary action |
| Enlarged text, including 18pt and the supported upper setting | Fields, tab/selector labels and state text grow; no clipped fixed-height rows; footer reachable |
| Content cannot fit side by side | Reflow using font/size hints: stack overview and persistent inspection regions or use an explicit overview disclosure; preserve selection and a clear route back, without nested card navigation |
| Long source/destination identities | Wrapping/selectable detail plus accessible full value; ordinary layout stays bounded |
| Many platforms/destinations/tasks | Scroll the relevant content region; do not create additional permanent navigation layers |
| Keyboard-only | Logical context → navigation → fields/list → inspector → footer order; every repair and graph task has an equivalent route |
| Focus after navigation | Reveal and focus the relevant field/task; closing a dialog returns focus to its invoker; updates do not steal focus |
| Native light/dark and higher-contrast appearance | All custom semantic colors, borders, focus and dimmed states remain distinguishable |
| Screen reader | Named controls, label relationships, selected/check states and important state changes available; timer ticks stay quiet |
| Reduced motion | No essential information depends on animated map following or continuous movement |

Keep the fixed footer, avoid scrolling the whole app just to reach Start, and keep
each large tree/text pane's scrolling deliberate. Two purposeful task/evidence
scroll areas are preferable to an additional outer inspector scrollbar. At small
sizes, avoid a web-style mobile navigation rewrite; this remains a desktop app.

The hierarchy/alignment recommendation follows Apple's general layout guidance;
its native platform examples are principles to adapt, not a requirement to copy
Apple-specific materials into a cross-platform Qt app.
[Apple layout guidance](https://developer.apple.com/design/human-interface-guidelines/layout).

## Implementation sequence after approval

| Slice | Changes | Completion evidence |
| --- | --- | --- |
| 1. Shared visual foundations | Shared scalable type/spacing, semantic status/focus treatment, footer hierarchy | Representative buttons/cards/forms in both themes and enlarged fonts; existing palette/action/accessibility contracts |
| 2. Shell and Choose work | Remove duplicate breadcrumb, localize presets, rebalance panes, Platforms label, flatten delivery groups, recipient layout and requirement treatment | Each intent, legacy operation, long labels, device recipients, preset round-trip and repair navigation at laptop sizes |
| 3. Review | Visible captured summary, evidence space, adaptive task list, clear scope and Start copy | Exact source/host/destination values, all tasks reachable, dependency jumps, invalidation and unchanged approval boundaries |
| 4. Progress and evidence | Unified evidence navigation, scope indicator, consolidated attention, Tests/Timing/Output/Files layout | Running/waiting/failure/cleanup/approval/unknown/saved states; selection, text and scroll stability |
| 5. Supporting tools | Setup, settings, accounts, machines, storage and command-panel layout/copy | Loading/save errors and unsaved edits; inert fixtures for maintenance/confirmations; no real device/provider operation |
| 6. Native acceptance and user guidance | Walkthroughs on authorized desktops, keyboard/accessibility/theme checks, updated operator docs | Explicit acceptance record by platform, with remaining native gaps stated |

Implement each slice as a reviewable change on the current branch, preserving
unrelated edits. Validate the changed presentation contract rather than adding
tests that merely repeat a spacing constant. Choose focused existing tests:

- Shell/intent: `test_toolbar_goals_ui.py`, `test_run_workspace_ui.py`,
  `test_guided_ui.py`, `test_choose_work_layout_ui.py`, `test_run_presets_ui.py`.
- Choices: `test_recipient_ui.py`, `test_workflow_options_ui.py`,
  `test_blockers_cards_ui.py`, `test_build_only_ui.py`, `test_proposed_workflow_ui.py`.
- Review/evidence: `test_review_workspace_ui.py`, `test_summary_reading_ui.py`,
  `test_dependency_flow_ui.py`, `test_scoped_run_ui.py`, and the affected
  inspector/state contracts in `test_review_workspace_ui.py`.
- Results/recovery: `test_results_overview_ui.py`, `test_running_states_ui.py`,
  `test_card_progress_ui.py`, `test_device_retry_ui.py`, `test_history_navigation_ui.py`,
  `test_approval_cards_ui.py` and relevant continuation/headless contracts.
- Supporting tools: `test_onboarding_ui.py`, `test_settings_async_ui.py`,
  `test_storage_ui.py`, `test_deployment_commands_ui.py`.
- Shared behavior: `test_action_hierarchy_ui.py`, `test_accessibility_pass_ui.py`,
  `test_palette_ui.py`, `test_live_responsiveness_ui.py`.

The dormant grouping/map code and tests remain preserved. Headless helpers must
remain free of Qt/project imports. No new sibling checkout discovery, interpreter
sharing or adapter policy inference is needed.

## Acceptance walkthroughs

These are proposed usability targets, not measured audit results. Use a first-time
operator and an experienced operator where possible; record confusion as well as
completion. Rehearse using synthetic or explicitly authorized harmless fixtures.

| Task | Passing observation |
| --- | --- |
| Add a project | Operator identifies the correct folder, understands registration scope and finds the next choice without reading descriptor JSON |
| Configure checks | Operator finds source, platforms and hosts in that order and can explain included/excluded edits |
| Configure delivery | Operator selects two destinations and their recipients/notes without losing the earlier destination's context |
| Repair a conflict | Operator understands which platform or recipient is missing and fixes it without other choices changing |
| Explain Start | Within about ten seconds of opening Review, operator identifies exact source, execution hosts, work starting now and later approvals |
| Inspect a dependency | Operator selects a destination and reaches its exact prerequisite without leaving the overview or losing selection |
| Diagnose failure | Operator finds the failing task/case, reads the error, and distinguishes the cause from downstream blocked work |
| Handle mixed outcomes | Operator can find an independent eligible delivery while seeing another branch's failure |
| Approve selected delivery | Operator identifies exact artifact/source/destination/recipients; only explicitly selected actions are approved |
| Inspect unknown outcome | Operator finds retained evidence and reconciliation guidance without being offered an unsafe generic retry |
| Reopen history | Saved results open separately; original draft remains intact and the saved plan cannot be started as a new run |
| Change settings | Search preserves edits, failed save preserves inputs, successful save invalidates applicable reviews |
| Inspect maintenance | Operator distinguishes refresh, setup, permission change, deletion and retirement before any effectful action |
| Resize/use keyboard | Core tasks remain usable at 1024×700, enlarged text and keyboard-only navigation, with native focus verified |

Do not claim the redesign is complete from screenshots or portable tests alone.
Record native layout, keyboard and assistive-technology acceptance separately.

## Source ownership and related briefs

| Area | Primary source |
| --- | --- |
| Shell, registration and tabs | `Python/build_manager/app.py` and pinned commonUtils workspace components |
| Stage composition and footers | `Python/build_manager/ui.py` |
| Configuration and per-run fields | `configuration_ui.py`, `configuration_delivery_ui.py`, `run_fields_ui.py`, `recipient_ui.py`, `presets_ui.py` |
| Overview and card presentation | `workflow_ui.py`, `workflow_cards_ui.py`, `workflow_map_ui.py`, `grouped_workflow_ui.py` |
| Review and inspection | `review_ui.py`, `run_ui.py`, `run_inspector_ui.py`, `run_output_ui.py` |
| History and approvals | `history_ui.py`, `approval_ui.py`, `continuation_review_ui.py` |
| Supporting tools | `project_setup_ui.py`, `settings_ui.py`, `application_settings_ui.py`, `accounts_ui.py`, `vm_ui.py`, `storage_ui.py`, `deployment_commands_ui.py` |
| Shared visual mechanics | `ui_components.py`, `palette_ui.py` |

The manager owns generic presentation/orchestration. Project adapters keep their
suites, source snapshots, release rules, destinations and storage policy.
commonUtils keeps shared UI APIs; update that ownership deliberately if a later
implementation genuinely requires a shared primitive.

- [Development home](development.md)
- [Current guided UI](../user/guided-ui.md)
- [Earlier review and progress brief](second-stage-ui-brief.md)
- [Earlier redesign brief](ux-redesign-brief.md)
- [Earlier implementation audit](ux-redesign-audit.md)
