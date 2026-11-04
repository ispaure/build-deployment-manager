# Developer experience audit and action plan — November 3, 2026

## November 4 integration status

The initial manager implementation, dependency integration and component
extractions are integrated. The original candidate's complete 101-module coverage
was collected across two batches, as documented in
[Current validation scope](validation.md#november-4-documentation-audit-and-integrated-validation)
and remains bound to that source rather than subsequent changes.

The later [Windows contract follow-up](validation.md#november-4-windows-offscreen-fonts-and-interpreter-cleanup)
identifies missing offscreen fonts as the cause of both sizing failures. Published
SDK `5d068f4` supplies the existing Windows system font directory to contract
children when no explicit directory or native platform was selected. All 40
affected Windows cases pass through the actual runner with unchanged UI
assertions. The two historical hosted interpreter-deletion errors initially did
not reproduce on the managed guest's different python-build-standalone runtime.
The matching natural hosted Windows job reproduces them with failure metadata;
a later managed check using the exact hosted MSVC Python and fresh venv executable
hashes also reproduces the bootstrap cleanup error. Published SDK `8ad92eb`
aligns those private test fixtures with the existing bounded owned-tree removal
policy, after capturing the first failure and strictly revalidating ownership.
Both original fixture methods and all 13 helper contracts pass on that matched
runtime, including a real first failure followed by logged bounded recovery.
Separate ordinary-subprocess and minimal SDK subprocess controls both reproduce
error 5. The underlying OS cause remains unknown; this is a qualified fixture
policy alignment, with no production transport change or ignored persistent lock.

The latest recorded Logistics consumer check is bound to source `f3166c7`, SDK
`8ad92eb` and commonUtils `66b9eed`: all 198 cases across 11 project-context
modules pass. Both private desktop and mobile environments retain their own
project commonUtils and immutable SDK roots in both import orders; source,
dependency pin and checkout status remain unchanged. This supersedes the earlier
130-case consumer receipt for SDK `5d068f4` without qualifying later source or the
complete 115-module SDK/hosted pipeline. Full hosted and native acceptance remain
separate. A separate Fedora run at Logistics `c5bd805` / SDK `8ad92eb` / commonUtils
`66b9eed` passes all 115 SDK modules; Windows and macOS full-suite qualification
remain pending at that checkpoint. The dated observations below describe their
original snapshots rather than today's registration or dependency state.

The separate [Fedora inspector follow-up](validation.md#november-4-fedora-inspector-containment-follow-up)
reproduces the exact 43-pixel pressure failure and verifies the candidate across
42 Fedora offscreen cases. It fixes ancestor overflow and stale task-row font
minima while preserving strict containment, repair/caption visibility and manual
split choices. These checks remain bound to the recorded source; the next full
hosted gates and native mobile acceptance are separate.

## Scope and conclusion

Reviewed manager `6be191b` plus the existing Android emulator working edits,
its real commonUtils submodule `7b17e5c`, and the selected Logistics checkout at
`aedaa595` with its existing application edits and commonUtils `93990e8`.
Inspected local registrations, descriptors, bridge source, dependency selection,
and the eight most recently modified retained run reports. This is a local
source and portable-contract audit, not new native or release acceptance.
Raw inventories and verification logs live under ignored `test-results/`.

Keep the three owners: the manager supervises generic work, Logistics supplies
application policy, and commonUtils supplies reusable primitives. The best next
improvements make those boundaries easier to discover and diagnose. Another
package-wide move would obscure the more immediate problems below.

## How Logistics is used now

There are four registered Logistics checkouts sharing one project identity.
The selected registration has both full validation/delivery presets and focused
development-device presets, including delivery without optional validation.
Therefore a project identity alone can be ambiguous; a registration name or exact
checkout identifies the intended environment. Registration settings and results
are checkout-specific. Saved choices do not authorize a new execution.

The current descriptor declares five platforms, seven named test suites, fourteen
run fields and twelve adapter actions. Host-specific operation maps distinguish
desktop checks, native mobile validation, builds, tester preparation and source
releases. Journeys combine selected checks, packages and destinations. Logistics
owns source capture, signing, required gates, device compatibility and retention.
See [tracing Logistics](logistics-integration.md) for the source path.

The declared manager dependency is `f72ca1e`; the project interpreter currently
resolves the editable manager checkout reviewed here. Retained reports also name
older engines, including `b78f1bf` and `2090c80`. These are separate observations:
a declared pin, an installed import location and a run's captured engine identity
answer different questions. Do not assume a new manager checkout retroactively
validated old artifacts or updated the consumer's declared dependency.

The eight-report sample contains four passed, two failed, one cancelled and one
unknown outcome. One failed run stopped at a DNS prerequisite; another contains
six failed JUnit validation phases. The unknown outcome records a device install
attempt against a locked device. This sample establishes use of both focused
device and combined delivery plans; it is not an overall success-rate measurement.
Nothing was replayed, approved or reconciled as part of this audit.

## Findings and ordered actions

| Priority | Evidence and developer cost | Action and acceptance | Status |
| --- | --- | --- | --- |
| P1 | `registry.read_project_descriptor` checked platform/operation lists, but nested backend and operation maps could reach discovery as strings or invalid shapes. Errors then occurred away from their source. | Validate discovery metadata before registration or adapter execution. Name the exact field; preserve API-1 fallback rules and explicit empty choices. Verify malformed and real consumer descriptors. | Implemented in this pass |
| P1 | `ProjectBridge.call` used `.get` on arbitrary decoded JSON. A JSON list/null raised an uncaught type error; invalid JSON and child exits lacked project/action context. | Report the project, action, bridge path and protocol expectation or exit code. Do not echo private stdout. Preserve redaction and valid result types. Test real isolated subprocesses. | Implemented in this pass |
| P2 | CLI `inspect` passed its selector directly to `Registry.resolve`, which accepts registration keys. Names/paths failed despite other discovery commands supporting them. Multiple Logistics checkouts expose the inconsistency. | Use the existing unique-selector resolver. Exercise names, paths, IDs and ambiguous worktrees without invoking the adapter. | Implemented in this pass |
| P2 | Broad validation exposed two timing-sensitive UI fixtures: the responsiveness test raced a 150 ms worker sleep, and the workflow test shared one 15-second deadline across preparation, artifact rejection, review and two executions. Both failed again on separate reruns. | Hold the planning worker with an event until the main loop delivers timer ticks; retain stale-selection rejection. Give each asynchronous workflow operation its own bounded 15-second wait. Preserve assertions for artifact rejection, approval and exactly one effect. | Implemented in this pass |
| P1 | `build_manager.__init__` prepends its source root. A Logistics interpreter probe with Logistics first on `PYTHONPATH` still selected manager commonUtils after manager import. Preloading Logistics commonUtils selected the consumer copy instead. The pins differ. | Decide and document the dependency contract for adapters running in consumer processes. Add subprocess acceptance for both import orders and report the actual loaded dependency. Keep standalone manager tied to its real submodule; do not silently redirect it to Logistics. | Addressed by explicit project context and loaded-dependency provenance in the three follow-up passes below |
| P2 | `ui.py` has 1,314 lines and a 263-line constructor; `run_ui.py` has 1,031 lines and a 262-line constructor; `configuration_ui.py` has a 317-line constructor. Existing session/state/inspector owners already provide seams, but construction and coordination remain hard to follow. | Extract one Qt view at a time using explicit inputs/signals: configuration section construction first, then run-summary/test presentation. Retain parent ownership, stale-worker guards, selection and approval rules. Use current lifecycle/accessibility/selection tests as acceptance; require native Qt acceptance for lifecycle changes. | Source/delivery and summary/test owners extracted in the three follow-up passes below; shared visual work remains separately owned |
| P2 | Historical audits contain old line counts, backend availability and acceptance totals alongside current guides. New developers must distinguish history from instructions. | Add a current Logistics trace and link this dated assessment from the developer landing and earlier audit. Keep current behavior in task/reference guides and raw evidence outside the wiki. | Implemented in this pass |

## Delivery sequence

1. Ship the descriptor, bridge and selector corrections with their focused tests
   and the current integration trace. Preserve Plan/Phase serialization, saved
   selections, dependency pins and the dormant nested card browser.
2. Resolve the adapter-process dependency contract before either shared API
   changes or a coordinated pin update. Test both import orders in fresh
   subprocesses with the two explicit checkouts and their own interpreters.
   A manager-only pass is insufficient.
3. Extract the configuration sections using explicit values/events, then run the
   preset restoration, recipient focus, source choice, accessibility and worker
   shutdown checks. Compare native desktop behavior before adopting the change.
4. Extract the results summary/test presentation using `RunState` facts. Preserve
   stable selection, bounded output, retained-run navigation and pending-review
   behavior. Keep `ReviewPlanView(nested_navigation=False)` in both stages.

Each follow-up should be a bounded review with behavior-based acceptance, rather
than a file-length target. No VM/device access, pin updates, publication or
dispatch is implied by this plan.

## Validation of the implemented changes

Focused coverage exercises capability shapes and fallbacks, rejection before
adapter execution, malformed subprocess responses, redacted child failures and
unique CLI selectors. All four registered Logistics descriptors pass static
validation. A selected-checkout check covers all three host maps, and a focused
consumer suite-routing fixture passes in Logistics' interpreter
with its commonUtils explicitly preloaded and this candidate manager.

The full portable/offscreen runner exercised all 100 manager modules. Its initial
run passed 97 modules and failed the CLI, general UI and workflow UI modules.
The CLI run exposed the new test's canonical-path assumption and a recovery test
failure while the shared checkout changed. All 23 CLI cases passed after the path
correction on a stable rerun. The UI reruns exposed the timing dependencies
described above; all 15 general UI cases passed after the event handshake change,
and the real pause/reject/review/resume workflow passed with operation-specific
deadlines. Thus all 100 modules have passing results, with three focused reruns.
The initial nonzero suite result and subsequent focused logs are retained; this
is not a claim of one uninterrupted green full-suite run. All 30 wiki pages pass
H1, relative-file-link and landing-page coverage checks.

Concurrent Android work was committed as `039f9ac` during this audit and received
further working edits. It remains a separate change; these fixes do not stage or
rewrite its emulator, test or host-guide files.

These checks do not establish native Windows/Linux GUI behavior, mobile readiness,
signing, provider state or release acceptance. Existing unrelated manager and
Logistics edits remain in place. No consumer files or private configuration were
edited.

[Developer guide](development.md) · [Earlier refactoring audit](refactoring.md)

## Three follow-up review and fix passes — November 3, 2026

The follow-up implements the remaining dependency and component boundaries above.
The original assessment and validation totals remain historical evidence.

1. **Dependency isolation.** Adapter subprocesses explicitly use project dependency
   context; standalone manager processes bind the manager source root. Fresh
   Logistics subprocesses resolve Logistics commonUtils in both import orders.
   Runtime provenance now records the loaded package's checkout. No consumer or
   manager pin is changed. The direct-tooling contract is documented in
   [the Logistics trace](logistics-integration.md#distinguish-the-three-dependency-identities).
2. **UI composition.** Source revision synchronization and delivery controls move
   into dedicated configuration views. Run summary and scoped test/timing views
   receive explicit plan/facts values and emit navigation requests. Coordinators
   retain preparation, approval and review policy. Existing named control handles
   remain available to callers. The concurrent, separately approved Balanced
   workspace implementation owns the shared layout/visual changes and preserves
   these extracted components; its full visual acceptance belongs to that work.
3. **Missed state and fixture contracts.** Test presentation resets its own cache
   when reopening identical retained facts. A changed scope updates column
   visibility even when final cases are identical; expired interim totals and
   deselected case details clear. Native Qt parents explicitly retain summary
   activity controls. Logistics' isolated journey fixture now mocks the current
   `capture_engine_source_identity` API instead of its unused compatibility alias,
   so its scheduling/approval tests actually have the fixed engine they declare.

Validation includes isolated import orders and bridge-context fixtures, an actual
Logistics read-only saved-recipient bridge request, all 24 isolated Logistics
journey cases, focused configuration/results tests and six native Cocoa result
cases. The first native attempt could not access a display from the sandbox;
the desktop-access run passed. This does not certify native mobile builds,
Windows/Linux GUI behavior, signing, personal devices or provider publication.
Raw per-pass evidence remains under ignored `test-results/`.

The import-order and UI ownership findings are addressed by these changes. Future
extractions should follow measured responsibilities rather than a line-count
target. The dormant nested workflow browser remains disconnected.

## Shared layout integration and final checks — November 4, 2026

The shared Balanced workspace now includes these extracted views. Its font
refresh has one application observer, avoiding cumulative per-heading event
filters. Review fixtures follow the instance-based engine-change dialog and the
visible source hint. Real child-process rendezvous replaces startup-sensitive
short sleeps in concurrency fixtures while retaining measured overlap and
prerequisite assertions. No execution or approval policy was relaxed.

The reviewed dependency merge preserves the release privacy fix and the newer
shared APIs. Standalone manager and Logistics checks continue to use separate
interpreters and their own real commonUtils pins. The complete manager module
coverage, fresh Logistics compatibility and native fixture scope are recorded in
[integrated validation](validation.md#november-4-documentation-audit-and-integrated-validation).
The release pause and later continuation are explicit in that record; the dormant
nested workflow browser remains disconnected.
