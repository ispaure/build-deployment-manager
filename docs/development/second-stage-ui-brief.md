# Clearer plan review and run progress

## Current UI decision

Review plan and Progress & results now share `ReviewPlanView`: a persistent
captured-card overview beside the task tree and Details / Command / Plan inspector.
Selecting every card follows the same rule: filter the side pane without opening
a nested map. All tasks clears that filter. Run-only test, timing, output and
delivery reports supplement the inspector under Results. Start retains the
selection and pane sizes, and live facts update the reviewed cards in place.
Best fit measures wrapped card layouts in both orientations using widths from
88% to 124% of the normal card width. It favors readable text before scaling the
map; explicit orientation and manual zoom retain control. Reflow keeps the same
card widgets and dependency identities.

The nested browser in `grouped_workflow_ui.py`, `PlanSummaryView` and supporting
grouping/map code are deliberately preserved for a later UX review and possible
improved reintroduction. `nested_navigation=False` unhooks it from both active
stages. **Do not delete this dormant view as unused code or reconnect it without
an explicit user request.** This preservation requirement is also in the root
`AGENTS.md`; the earlier design discussion below records the superseded proposal.

Portable Qt tests cover both stages, consistent leaf/multi-task selection,
frozen overview geometry, live facts, cross-card prerequisite selection, report
inspection and reset. Offscreen screenshots are layout checks, not native desktop
or screen-reader acceptance. Raw evidence remains under ignored test-results.

## Earlier design decision (superseded)

After **Next: review plan**, open a readable confirmation of the user's choices,
the work that Start authorizes, and the actions that require later approval.
Use the same high-level card visuals as Choose work, with exact subtasks inside
each card. Keep the complete execution graph available for deeper inspection,
and carry the card interaction into Run and results.

The primary scope is **Review plan**,
the second guided page after configuration. Progress, approval and failure states
are included so the handoff from review remains understandable. Configuration,
project settings and the execution engine retain their existing responsibilities.
This refines the review portion of the [redesign brief](ux-redesign-brief.md).

## Earlier desktop implementation (superseded)

The native Qt implementation now opens Review on Run summary, with three
captured-choice columns above the familiar Source, platform, package and
destination cards. Clicking a card opens its subtasks in place with a resizable
list/detail splitter; All workflow cards returns to the overview. Exact steps
and dependencies and Technical details are desktop tabs; the existing resizable
stage browser, map and inspector remain intact. The Back/Start footer stays
outside the summary scrollbar. This is a desktop window layout, with no mobile
navigation or phone breakpoint.

`plan_summary.py` supplies headless presentation data; `plan_summary_ui.py` renders
it for review and run results. Summary rows use the declared platform gates and
external effects, including dispatches and their dependent work.
`grouped_workflow.py` attaches resolved tasks to the captured Choose work graph.
It preserves the original card IDs, labels, descriptions, positions and arrows.
Execution-order edges never split overview cards or generate new overview columns.
Platform lifecycle and cleanup tasks stay inside their platform card; package
labels and declared destination steps associate the remaining work. Shared tasks
can be referenced from more than one card. Unmapped tasks remain available from
Other resolved subtasks rather than silently disappearing or expanding the graph.

The configuration proposal is frozen when inspection starts, redacted and cached
against the resulting plan identity. Review and the current run reuse that exact
proposal. Older retained runs without a cached proposal reconstruct one from their
retained choices and the available descriptor; they never use current form choices.
Source can show captured identity with no executable subtasks when source capture
already happened during planning. No command text is used to infer card ownership.

`grouped_workflow_ui.py` reuses the configuration FlowCanvas, icons, card dimensions,
arrows and Fit/zoom behavior. During Review, counts appear in tooltips and the open
card so they do not inflate the overview. The subtask drawer explains exact
prerequisites and cross-card scheduling waits. The full technical dependency map
remains available for inspecting every execution edge. Recipient cards remain in
the captured layout; when the adapter does not declare action-to-recipient mapping,
they explicitly reference the destination's shared actions without guessing identity.

Run results reuse the cards with measured outcomes and waiting reasons, while
overall guidance and reported case counts remain independent of step selection.
Existing retained verification and the approval dialog still own continuation;
this pass does not add per-destination execution buttons.

Portable contracts cover frozen graph parity, cross-platform order-only waits,
platform cleanup, shared references, headless imports, keyboard drilldown, live
updates and reset after inspection. A read-only native Cocoa preview of the retained
52-step Logistics plan verifies the same 19 Choose work cards, identical node
positions and arrows, all 52 tasks mapped, and 16 iOS subtasks inside the iOS card.
The plan identity remains unchanged and no commands are started. Earlier compact
fixtures cover 1280×800 and 1024×700 sizing. Native screen-reader and real-provider
acceptance remain separate. Raw evidence stays under ignored test-results.

## User and success criteria

An occasional operator has already chosen source, platforms, execution locations
and destinations. Before starting, they should be able to answer:

- Which exact source and platforms did I choose?
- What will this button start, and where will that work run?
- What will need my approval later?
- If something fails, which destinations are affected and what can I do next?

Target: in a short walkthrough, the operator can answer the first three within
ten seconds without opening technical details. This is a usability acceptance
target, not a measured result.

## Earlier presentation and the clarity problem

The current `ManagerPanel` review page has a short context label, optional run
inputs, a stage browser or dependency map, a persistent plain-text inspector,
technical tabs behind a checkbox, helper text and Back/Start controls.
`present_plan` builds a detailed summary, while `review_step` also places it in
the inspector when no step is selected. `WorkflowFlow` already supports grouped
steps, exact dependencies and selection shared with execution.

| Current structure | Design implication | Proposed change |
| --- | --- | --- |
| Whole-plan context and step detail share an inspector | The most useful summary is presented like diagnostic output | Keep a concise run summary above the workflow |
| Large plans begin with collapsed purpose groups | The operator must explore to discover the practical outcome | Put human-readable outcomes and approval boundaries on visible group rows |
| Several representations expose overlapping information | It is unclear which view is necessary to approve Start | Default to Run summary; provide Exact steps and Dependency map as alternate detail views |
| Captured notes use a separate plain-text box | Destination identity, recipients and notes can be visually separated | Put captured values under their destination; shared values appear once |
| Long Start wording and explanatory text compete for attention | The action's scope requires reading several places | Use one primary action with a scope sentence immediately beside it |

These are design hypotheses grounded in the current source and
[guided UI](../user/guided-ui.md), rather than findings from a new operator study.
The existing stage browser is useful and should be reused.

## Recommended layout

Keep the native Qt application, project chrome, text-size preference and the
Choose work → Review plan → Run and results breadcrumb. Past runs stays separate.

1. **Page heading:** “Review your run”, followed by “Ready to start” or the
   specific reason Start is unavailable.
2. **Captured choices:** source mode and immutable identity, dirty status when
   applicable, selected platforms with their execution locations, and the
   project-provided release identifier when present. Show full identity on demand.
3. **Workflow cards:** reuse the first page’s card visuals for Source, platforms,
   preparation and destinations. Each card shows its subtask count and aggregate
   state. Clicking opens its subtask list and details in place; All workflow cards
   returns to the overview. Shared work is represented once. Approval requirements
   stay visible on external-action cards. Independent work remains eligible to
   overlap, subject to scheduling and resource limits.
4. **Destination context:** exact destination identity, recipients, notes and
   relevant captured overrides. Keep these visible before the action they qualify;
   long notes can expand. No credential contents or arbitrary provider URLs.
5. **Detail disclosure:** “Inspect exact steps” opens the existing grouped browser
   and a step inspector. Dependency map remains available here. Raw commands,
   resource locks, timeouts, dependency table and redacted plan stay under
   “Technical details”. Every phase remains reachable.
6. **Action footer:** “Back to choices” and one primary action. For the integrated
   delivery example: “Start validation and preparation”, with “Uploads wait for
   your approval.” Keep the action reachable at normal laptop sizes.

Do not imply that the summary's vertical order schedules execution. Use wording
such as “Each package waits for its required checks”; the exact graph remains
authoritative. Display cleanup and inspection groups when supplied by the plan.

## Alternative layout

**Outline and inspector** keeps a resizable split view: an expanded outline with
short purpose summaries on the left, contextual details on the right, and the
captured choices above both. It favors frequent operators examining complex
plans. The recommended **Summary first** layout gives occasional users a calmer
entry and reveals the split view only when requested. Compare comprehension and
step-finding time before selecting the default; avoid adding another permanent
layout preference in the first implementation.

The accompanying interactive mockups show both layouts using synthetic Logistics
content, identities, timings and counts. They illustrate presentation rather than
an adapter's available destinations or a real execution result.

## State and action contract

| State | Main message | Primary action and behavior |
| --- | --- | --- |
| Preparing plan | Resolving source and checking requirements | Keep configuration visible with its current progress and cancellation behavior; disable duplicate requests |
| Ready for review | Ready to start; source and action scope visible | Start validation, Start checks, or Start validation and preparation, derived from the actual plan |
| Review invalidated | Choices or settings changed; prepare a fresh plan | Return to choices; old Start becomes unavailable immediately |
| Preparation failed | Explain what needs correction near the configuration action | Preserve choices and existing source-policy routing |
| Running | Current work and why other work is waiting | Keep Cancel available; no second Start |
| Waiting for resources | Waiting for the named resource or concurrency slot | Explain the reason separately from a failed dependency |
| Ready for approval | Prepared output and eligible destination need review | Review prepared delivery opens existing verification and effect approval; it does not itself deliver |
| Partial failure | Name failed work and affected destinations | Inspect failure; independently eligible destinations remain reviewable |
| Cancelled or interrupted | Work stopped or its outcome needs investigation | Offer existing recovery only when eligible; never imply automatic retry |
| Unknown external outcome | Check the retained outcome before continuing | Expose retained evidence; block unsafe repetition through current recovery rules |
| Complete | State actual outcomes per platform and destination | Open retained results; provider acceptance and tester availability stay distinct |
| Saved run | Viewing a saved run with its original source | Read-only inspection; continuation is a separate recovery action |

During execution, keep source and destinations anchored while updating the work
rows in place. Show status words, measured durations and the current reason.
If a progress counter appears, label it “steps finished”, including failures and
skips. Keep reported test-case counts separate; missing reports mean “No case
report available”. Never use a step percentage as a success rate or invent an ETA.

Selecting a row changes the inspector without changing the overall run heading
or destination summaries. A failed prerequisite explains the affected pending
work as “Blocked by …”; the executor's eventual skipped outcome remains distinct.
Cleanup can still run after failure when declared. Zero eligible deliveries must
not produce a generic Review delivery action.

## Approval and compatibility requirements

“Starts now” must be calculated from the actual effects and approval gates. A
GitHub `dispatch` is an external action even when its purpose is testing; show
“Launch GitHub checks — approval required” at its actual gate. Never present it
as unconditionally authorized by local Start. Legacy whole-plan external
operations retain their explicit confirmation and use their declared scope.

Approval must show exact prepared artifacts, source, destination, recipients,
notes and dependency evidence. Revalidate through the existing review session;
changed artifacts or stale selections cannot approve work. A successful test or
an available approval action is not permission to upload, publish or dispatch.

The manager owns presentation and orchestration. Project adapters supply plans,
labels, release rules and destination policy. Use current fields first; missing
metadata gets a truthful fallback. No new manager inference from command strings,
new adapter requirement, credential mechanism or commonUtils fork is needed.

## Implementation sequence

| Slice | Work and owner | Completion evidence |
| --- | --- | --- |
| 1. Readable review | Extract the captured summary and scoped action copy from `ui.py` into a review presentation component; preserve session ownership | Review fixtures cover test-only, integrated delivery, legacy and hosted dispatch plans |
| 2. Workflow detail | Reuse `workflow_ui.py` groups and exact map behind a disclosure; preserve selected phase across views | Every phase reachable, cross-view selection retained, long labels and large plans readable |
| 3. Run continuity | Apply the same summary/group structure to `run_ui.py`; retain existing Results, Tests, Timing and Output inspection | Harmless process fixtures cover concurrent work, resource wait, failure, cleanup, cancellation and report hydration |
| 4. Review and recovery | Put eligible destination actions and blocking reasons near their rows, using current review/recovery APIs | Existing stale-review, artifact verification, independent-branch and unknown-outcome contracts continue to pass |
| 5. Native acceptance | Inspect actual Qt layout and keyboard flow on an authorized desktop; update user guidance after implementation | Review and run remain usable at 1024×700 and 1280×800 with enlarged text; native accessibility checked separately |

Each slice should leave a usable workflow. Preserve unrelated working-tree edits.
Keep headless summary/state helpers free of Qt and project imports. Do not change
execution ordering, dependencies, retries, retention or source snapshot policy to
make a visual grouping easier.

## Validation and acceptance

Portable tests should verify changed contracts: summary values match the retained
plan; editing selections invalidates Start; hidden details do not hide phases;
dispatch keeps its approval gate; selection preserves context; history never
enables Start; failed branches do not disable independent eligible delivery.
Use temporary projects and harmless commands. Relevant existing test modules
include `test_guided_ui.py`, `test_dependency_flow_ui.py`, `test_review.py` and
`test_accessible_flow.py`; choose additional tests according to changed behavior.

For visual acceptance, check ready, long-plan, validate-only, dispatch approval,
running, resource wait, partial failure, approval, unknown outcome and saved-run
states. Use native controls, readable contrast, visible focus and status text
alongside color. On narrow layouts, stack summary and inspector; keep long source
identities and destination values reachable without horizontal page scrolling.
Return focus predictably when opening details or returning to choices; announce
important state changes without announcing every timer tick.

Run a short task walkthrough: identify source and execution hosts; explain Start;
find the exact prerequisite of a delivery; inspect a failed check; review only an
eligible destination. Record misunderstandings before implementing the alternate
layout. Portable fixtures and browser mockups do not establish native Qt or real
provider acceptance. Raw screenshots and test evidence belong in ignored
`test-results/`; no live delivery is needed to accept this UI work.

## Related design and contracts

- [Development home](development.md)
- [Guided UI implementation plan](ui-improvement-plan.md)
- [UX implementation audit](ux-redesign-audit.md)
- [Integrated journey contract](journey-contract.md)
- [Validation guide](validation.md)
