# UX redesign brief: validation and coordinated delivery

## Decision and intended outcome

Replace the preset-first configuration form with a guided journey built around
two goals: **Validate** and **Validate and deliver**. Users choose what to check,
which platforms to check, and where prepared outputs should go. The app explains
the resulting order before execution and keeps the same journey visible through
testing, preparation, approval, delivery and results.

The main success criterion is that a non-technical user can answer, without
reading logs: “What will run? On which platforms? What happens next? What needs
my attention? What has actually been delivered?”

This document is an implementation brief, not a claim that these changes have
shipped. It follows the existing [guided UI implementation plan](ui-improvement-plan.md)
and replaces its preset-first interaction recommendation for the next iteration.
The current [usage guide](../user/guided-ui.md) describes today's behavior until the
redesign is implemented. No release, upload or device action was performed for
this assessment.

## Evidence and limits of the assessment

Assessment used the current manager source, documentation and harmless offscreen
Qt fixtures. It did not inspect a live project adapter, personal settings or a
running native app window. Therefore project-specific destination availability,
actual preset contents and the reported Settings failure still require native
reproduction. Raw fixture output is retained under ignored `test-results/ux-audit`.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| A workflow preset fills one platform, operation, backend and optional suite | `ManagerPanel.select_preset` in `Python/build_manager/ui.py` | A preset behaves like a saved form, although its name suggests an enduring goal |
| Editing platform, operation, backend, suite or advanced fields can reset the preset | `ManagerPanel.invalidate`; fixture reproduced Android preset → iOS → Custom operation | Users lose the label explaining their intention without a meaningful explanation |
| Platform is a single-choice combo box | `ConfigurationView` in `Python/build_manager/configuration_ui.py` | There is no first-class request to validate several platforms together |
| Execution stages and History are peer numbered tabs, with nested review/result tabs | `ManagerPanel`, `RunView` | Navigation mixes a sequence, an archive and diagnostic detail |
| Setup/maintenance actions occupy prominent rows | `ManagerWindow`, Configure button row | Registration, trust, accounts, test machines and cleanup compete with everyday work |
| Settings data is fetched while constructing the dialog, before `exec()` displays it | `SettingsDialog`, `ProjectBridge.settings_view` and `ProjectBridge.call` | The GUI can appear unresponsive while a project subprocess runs; the bridge timeout is 300 seconds |
| Settings failures have limited presentation | `edit_settings` catches `OSError`/`ValueError` into a status label | Some errors are easy to miss; other exception types lack a local actionable error presentation |
| Basic Settings rendering succeeds in isolation | Fixture constructed a one-category dialog and verified visible field/page | The user's exact symptom is unresolved; do not label it a confirmed rendering defect |
| Engine already supports dependency graphs, bounded workers and artifact-scoped approval | `models.py`, `executor.py`, `workflows.py` | Coordinated delivery should extend existing orchestration rather than add a separate execution engine |
| Current bridge planning accepts one target and operation | `ProjectBridge.make_plan` | Multi-platform journeys require an adapter contract change or an explicit project-owned integrated plan |

The Settings loading path is a plausible explanation, not a confirmed root cause.
Native diagnosis must check trust, project interpreter availability, adapter
stderr, empty settings responses, window placement and startup exceptions.

## Product principles and scope

- Ask about intent before exposing execution mechanics.
- Explain order and consequences beside the relevant choice.
- Preserve user choices; show incompatible choices with reasons.
- Distinguish an unavailable feature from an unconfigured feature.
- Keep normal tasks concise and technical detail available on demand.
- Derive the preview, execution board and approvals from the same inspected plan.
- Show real outcomes for each platform and destination; an upload is not proof
  of installation, tester availability or successful device validation.

The manager owns the generic journey, settings mechanics, plan display,
scheduling, approval, recovery and history. Projects own supported combinations,
suites, source policy, release policy, destination identities, signing and storage.
Shared UI APIs belong in the pinned real commonUtils submodule only when they are
actually reusable. Keep Qt and project imports out of headless manager contracts.

Do not add automatic publishing after a passing test, guessed provider commands,
arbitrary command editing, store submission, or hidden execution-host fallback.
This brief authorizes design and planning; native acceptance requiring VMs,
devices or live providers needs explicit applicable authorization.

## Information architecture

Use three primary destinations: **New run**, **Runs**, and **Setup**. Keep the
selected project name and checkout visible in a compact header. Put add/locate/
remove registration and trust management in a project menu or first-run setup.
Adding a project authorizes its adapter; separate trust prompts are no longer required.

New run contains four stages: **Choose work → Check readiness → Review plan →
Run**. These are a stepper with completion/current/blocked states. Runs is an
independent archive, not “step four.” Opening a past run shows a conspicuous
viewing-history banner and its original project/source identity.

Keep one prominent next action per stage. Back preserves valid choices. Before
execution, changing a choice invalidates the inspected plan and explains the
change. During execution, editing the draft cannot mutate the active run; the
initial implementation can simply prevent editing active-run configuration.

Setup contains project settings, connected accounts, execution hosts and storage
maintenance. Provide a persistent **Settings…** entry, including from run views.
During a run, settings may be viewed; editing execution-sensitive values follows
the existing activity lock. Each blocker links directly to its relevant setup
section and returns to the user's draft afterward.

## Stage 1: choose work

### Goal

Offer two descriptive options:

- **Validate** — Run the selected checks. No release, upload or device install.
- **Validate and deliver** — Run required checks, prepare outputs, then review
  delivery to the destinations you choose.

Retain **Advanced operation** for legacy adapters and specialist tasks. This is
an intentional mode, never a silent fallback when someone changes a platform.
Choose a safe default for a new draft: Validate, with no destinations selected.

### Platforms and checks

Show a project-declared list of platforms with checkboxes. Each row includes
readiness, a plain-language check description and execution location. Separate
the target platform from where the job runs: “iOS checks · This Mac” or “Windows
checks · Configured test machine.” Technical backend identifiers belong in detail.

Offer **Recommended checks** using project-declared suites. Explain quick/focused
checks where supported and clearly state when they do not satisfy delivery gates.
Required release checks appear as included requirements. A focused run cannot
silently count as full release validation. No platform is counted as validated
merely because it has no available runner or individual case report.

### Delivery destinations

For Validate and deliver, show independent destination selections, grouped by
applicable platform/artifact:

| Destination concept | Required visible context |
| --- | --- |
| GitHub release | Repository, project-declared release mode, tag/version and included assets |
| Firebase tester distribution | App identity, supported platform/package and tester groups |
| TestFlight upload | App identity, build/version and declared testing audience if available |
| Install on test devices | Explicit selected devices, target platform and intended action |

These are examples of project capabilities, not hard-coded promises that every
project supports every provider/platform pairing. Firebase availability must come
from the adapter. Do not assume selecting iOS mandates TestFlight or excludes
Firebase. Device installation is its own destination, separate from cloud upload.

Unavailable destinations remain visible where useful with a concrete reason and
repair action. Example: “TestFlight requires an iOS build and a configured account.”
Selecting a destination can reveal required platform checks; adding them requires
an explicit visible choice. Do not silently add platforms, discard destinations or
substitute a provider. A conflicting edit retains the user's draft and blocks
progress until resolved or explicitly removed.

### Templates and customization

Rename presets to **Saved workflows** or **Suggested workflows**, subordinate to
the goal. Applying one previews the platforms, checks and destinations it sets.
Retain its name while compatible values change; display “Modified” with a small
change summary and Restore defaults action. An incompatible change explains the
conflict beside the affected selection. Avoid an automatic switch to Custom.

Legacy presets still fill their declared single-target values through a labeled
compatibility path. Do not infer missing destination semantics from preset names.

### Source and release details

Show a compact source summary at all times. Default validation source follows
project policy; delivery requirements must be visible before work starts. Put
revision selection and focused patterns in advanced detail, but promote required
release tags/version inputs into the main delivery form. Do not hide a blocking
release field behind Advanced options.

Label scope explicitly: **This run only**, **Saved for this checkout**, or
**Tracked source change**. Move tracked version editing into a distinct release
action with a clear explanation of files changed and any commit requirement.

## Stage 2: check readiness

Display a checklist grouped by selected work: source, project trust, interpreters,
hosts, test prerequisites, signing and destination connections. Show Ready,
Needs setup, Unavailable, or Not checked, using text and icons as well as color.
Each issue names the blocked work, why it is blocked, and a direct repair action.

Example: “iOS delivery needs signing setup. Open iOS signing settings.” Retain
the draft when repairing setup. Checks irrelevant to selected work must not block
validation; a missing TestFlight account should not prevent portable tests.

Separate descriptor inspection from execution of trusted project checks. Any
verification that runs project code or contacts a provider must be declared and
clearly identified. Readiness is not proof of future delivery success.

All loading and checking runs asynchronously with progress, bounded timeouts,
cancellation and visible error states. Stale responses cannot overwrite a newer
selection. Start plan preparation only through the stage's explicit action;
explain that it may prepare a source snapshot or allocate project-owned resources.

## Stage 3: review the actual sequence

Replace the default plain-text plan dump with a readable summary and dependency
lanes. Retain redacted JSON and commands under Technical details.

The summary states project/source, selected platforms, required checks, build
identities, exact destination identities, approval points and parallelism. Show
required checks even when the user did not choose them independently. Explain
whether successful validation is reused and how identity is verified; otherwise
state that the integrated journey will run its checks again.

Conceptual layout for a project that declares a common validation barrier:

```text
Project and source                  Goal: Validate and deliver
Platforms: Android, iOS              Destinations: 4 selected

Validate Android ─┐
Validate iOS ─────┴─ Required checks pass
                        │
               Prepare declared outputs
                        │
                  Review delivery
                        │
                 Eligible branches
                  ├─ GitHub release
                  ├─ Firebase distribution
                  ├─ TestFlight upload
                  └─ Install on selected test devices

[Back]                         [Start validation and preparation]
```

This is a design example, not a universal execution graph. Render the real
dependencies: projects can require a GitHub release before another destination,
build before testing, or separate platform preparation. Always show when a branch
is sequential, parallel-capable, awaiting approval or waiting for a shared resource.
Do not describe a topologically ordered step list as an exact serial schedule.

The start button describes what it starts. For Validate, use **Start validation**.
For an integrated workflow, use **Start validation and preparation**, with the
nearby text “Delivery pauses for your review.” Legacy whole-plan external effects
retain their existing confirmation behavior and an explicit explanation.

## Coordinated delivery and parallelism

The intended experience is one journey with several destination outcomes. “In
parallel” means independent approved work may overlap when dependencies, provider
constraints, worker limits and resource ownership allow. It does not mean every
network request starts simultaneously or that all destinations form a transaction.

Prefer a project-declared common required-validation barrier for a coordinated
release: if any selected required gate fails, delivery stays blocked. If a project
supports independent platform release, it must declare that alternative explicitly
and the UI must explain which failed platforms do and do not block each branch.
The manager must not rewrite release policy to make a selection runnable.

Build each declared artifact once and reuse that verified identity across compatible
branches. Different signing/package requirements may require separate outputs;
never imply that all destinations receive byte-identical files unless verified.

Before delivery, show one understandable checklist of ready external steps,
their retained artifact identities, recipients/devices and effects. The user
selects the actions to authorize and confirms with a concrete label such as
**Approve 3 selected delivery actions**. Approval must still create distinct
artifact-bound authorizations for each exact step. Only include steps whose
prerequisites are currently verified; later-dependent effects need later review.
The existing engine remains the authority for eligibility and revalidation.

Declining approval keeps the prepared run available. Changed source, settings,
artifacts or destination identity invalidates approval. Session-only approvals
are not restored after restart. A grouped UI does not grant blanket authorization
for future steps or altered plans.

If one destination fails, show the others' actual outcomes. Independent branches
may continue under the declared policy; cancellation requests owned cleanup and
can leave completed external actions in place. Do not promise rollback. Retry
only eligible unfinished work; never repeat a successful upload or blindly retry
an unknown external outcome. Unknown outcomes require provider reconciliation.

## Stage 4: run, results and recovery

Keep the journey summary and source identity above a compact board. Group rows
by platform and destination, with expandable technical steps. Put tests and logs
inside relevant detail rather than requiring users to navigate nested tabs to
discover the next action.

| State | Required explanation / main action |
| --- | --- |
| Checking or preparing | Current task, elapsed time, cancellation |
| Waiting for execution host | Named host/resource and reason |
| Validation failed | Failed platform/check, delivery impact, View failures |
| Ready for delivery review | Prepared outputs and pending recipients, Review delivery |
| Delivery running | Separate destination progress and dependencies |
| Partially delivered | Exactly which destinations succeeded, failed or remain blocked |
| External outcome unknown | Possible completed effect, Reconcile outcome; retry blocked |
| Interrupted harmless work | What can be safely reused, Resume unfinished work |
| Artifacts expired or changed | Why continuation is blocked, Prepare a new run |
| Complete | Actual validation and delivery outcomes, receipts/evidence and next actions |

Use counts such as “2 of 3 validation groups passed; 1 failed” and “2 of 4
destinations delivered.” A finished-step percentage is never a success percentage.
Distinguish a skipped check, an unavailable platform and a passed check. Individual
cases are available only when the adapter supplies typed reports.

For TestFlight and similar providers, report the strongest confirmed state:
“Upload accepted; processing pending” must not become “Available to testers.”
If follow-up status is unsupported, say so. Device rows distinguish package
installation from any project-declared launch/validation acceptance.

Runs retains goal, platforms, source, outcomes by destination, timestamps and
duration. Open a run read-only; offer explicit recovery on that retained run.
Continuing it must not depend on the current New run draft. A new delivery from
older validation evidence requires verified project policy and identity checks,
not an inference from a green historical row.

## Settings reliability and redesign

Treat the reported non-opening Settings action as the first implementation
priority. Diagnose the actual failure before claiming it resolved.

1. Display the Settings shell immediately with selected project/checkout and a
   visible loading state. Fetch settings through the isolated project bridge in
   a worker; keep all Qt widget construction on the GUI thread.
2. Provide cancel/retry and a useful timeout message. Closing Settings cancels or
   retires its request safely; stale replies must not populate a new project.
3. Present failures inside the dialog: invalid project registration, missing interpreter,
   unavailable adapter, malformed response or load timeout. Keep redacted diagnostic
   details expandable. Unexpected failures must also produce a visible error.
4. Handle an empty settings schema explicitly: “This project exposes no editable
   settings,” with links to accounts/hosts where applicable.
5. Use understandable categories based on declared capabilities: General,
   Validation and hosts, Signing, Delivery destinations and Storage. Keep account
   references and field origins discoverable without making them the main form.
6. Provide descriptions, sensible browse actions, inline validation, unsaved-change
   handling and visible save completion. Failed saves retain entered values.
   Save asynchronously; explain which checkout/profile receives changes.
7. Keep secrets as protected references. Show enough destination/account identity
   to prevent wrong-target delivery without displaying credential contents.
8. Remove ambiguity between saving settings and editing tracked app version;
   make the latter an explicitly separate source-change action.

Native reproduction must click the real Settings button from the affected
project, inspect UI responsiveness, verify the dialog comes to the foreground,
and exercise successful load, failure, save, cancel and reopen. Fixture success
alone cannot close the user's report.

## Implementation contracts and work packages

| Priority / package | Scope and exit criterion |
| --- | --- |
| P0 — Settings reliability | Reproduce actual symptom; asynchronous load/save, visible errors and empty/loading states; button always produces visible feedback |
| P0 — Selection integrity | Preserve workflow intent and show conflicts; no silent Custom transition or hidden backend substitution; every material change invalidates review |
| P1 — Guided single-platform journey | Goal-first navigation, readiness, contextual release fields and destination summary; legacy adapters remain usable |
| P1 — Multi-platform request contract | Versioned descriptor/request data for platform sets, suites, destinations, policy and supported combinations; old bridge requests remain supported |
| P1 — Project adoption | Owning projects emit one integrated plan with explicit dependencies, artifacts, recipients and gates; unsupported combinations fail clearly |
| P1 — Review and delivery board | One actual graph drives preview/run state; grouped review preserves per-step authorizations and independent destination outcomes |
| P2 — Recovery and history | Partial success, unknown outcomes, retained approvals/evidence and safe continuation are understandable without raw JSON |
| P2 — Usability/accessibility polish | Keyboard navigation, responsive layout, screen-reader labels, useful empty states and non-technical terminology |

For the new contract, distinguish **draft intent**, **inspected immutable plan**,
**retained run** and **current UI view**. Stable IDs connect platform, suite,
destination, phase and artifact metadata; display labels never choose commands.
Define supported-combination validation before execution. Metadata should be
inspectable without importing project code; dynamic checks still require trust.
Never concatenate separately prepared single-platform plans and assume they share
source snapshots, version allocation, output identities or release gates.

Extend scheduler behavior only where acceptance exposes an actual contract gap.
Existing `Plan.max_workers`, dependencies, capacities, resource locks and recovery
should remain authoritative. Presentation must not invent a second scheduler.
All new provider/destination semantics require project-owned adoption and receipts.

During migration, preserve existing registrations, settings layers and history.
Retain Advanced operation for older projects; label missing capability explicitly.
Do not migrate a preset name into a delivery authorization. Update current usage
guides when behavior ships and link every new documentation page from its landing.

## Acceptance and verification

Portable automated acceptance uses temporary descriptors/adapters, harmless
commands, fake provider receipts and controlled delays. It must cover:

- Multi-platform validation produces one understandable journey with no external
  effects; unavailable platforms cannot become silent skips or passes.
- Editing an Android distribution selection to iOS preserves goal/context, shows
  declared compatibility and an actionable conflict where applicable, and never
  silently changes to Custom or a different provider.
- Supported coordinated delivery includes GitHub, tester upload and selected
  test-device branches; all project-required gates block the correct effects.
- Independent approved branches overlap only within declared capacity/resource
  constraints; dependent branches wait and explain why.
- A required failure, optional failure, cancellation and skipped check have
  distinguishable outcomes and delivery impact.
- One failed destination preserves successful receipts; unknown outcomes block
  duplicate effects; artifact or plan changes invalidate approvals.
- Group review authorizes only selected eligible steps with exact identities;
  later prerequisites and restart still require applicable review.
- Slow, failed, empty and malformed settings loads remain responsive; switching
  projects, closing the dialog and late responses do not corrupt state. Failed
  saves preserve input; saved changes visibly invalidate affected review.
- Historical results retain original source/destinations and cannot run a stale
  draft. Legacy adapters and existing persisted data remain supported.
- Headless imports remain Qt/project-free; project runtimes remain isolated and
  the pinned commonUtils identity is preserved.

Native UI acceptance separately checks real window activation, readable layouts
at 1280×800 and larger, high-DPI scaling, keyboard focus, accessible labels,
long destination names and visible loading/error states. Store screenshots and
raw evidence under ignored test-results. Native device/provider acceptance is
separate, authorized work; portable fixtures cannot certify actual delivery.

Usability target: test with five people unfamiliar with the app. At least four
should complete each setup-ready scenario unaided: validate two supported
platforms; configure a declared coordinated release; recover from one failed
destination; and find/fix a setup blocker. Before Start, each should correctly
identify selected platforms, recipients, approval timing and what may run in
parallel. Treat any wrong-recipient expectation as a design failure. These are
proposed acceptance targets, not measured results.

Release the redesign after P0 reliability checks, integrated fixture contracts,
native UI acceptance and these comprehension checks pass. Track live project
delivery acceptance separately by exact source/artifact identity and destination.

## Decisions to settle during implementation

The recommended UX is specified above; remaining factual questions belong to
project capabilities: which platform/provider combinations exist, which gates
are shared, which destinations depend on a published GitHub release, what device
groups are authorized, and which hosted states can be reconciled. Resolve them
with owning adapters rather than asking users to assemble technical operations.

The first reviewable implementation should demonstrate Settings opening and
failure handling, one clear validation journey, and the Android/iOS selection
conflict using harmless fixtures. Then add the versioned multi-platform contract
and coordinated destination behavior. This gives the user an immediately clearer
path while keeping the full validation-to-delivery outcome as the completion goal.

- [Documentation home](../docs.md)
- [Current guided UI](../user/guided-ui.md)
- [Workflow review and recovery](../user/workflows.md)
