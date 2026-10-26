# Validation scope and remaining acceptance

## October 26 delivery approval cards

Delivery approval now presents only the exact eligible actions as unchecked cards,
with retained destination identities, captured scoped recipients and package
choices. Each card lists only its transitive prerequisite artifacts, with file
names and SHA-256 fingerprints; recognized scalar package/version/build fields
from retained JSON are display hints, never approval authority. Full paths,
checksums, source/settings and redacted JSON remain under collapsed Technical
evidence. Missing declarations stay explicit. Selected outlines, approval badges
and a persistent counted action footer match the workflow's visual hierarchy.
Cancel remains the default and existing artifact-bound verification is unchanged.

Six new contracts cover eligible scope, recipient isolation, prerequisite artifact
ownership, retained/redacted identities, explicit selection, disclosure and
small-window layout. The full portable suite passes 309 tests; 33 focused approval,
guided UI, action hierarchy and asynchronous continuation checks also pass with
native macOS Cocoa. Synthetic native captures at 850×650 and 640×540 with 14-point
text show unselected/selected cards, recipients and expanded evidence. These
validate presentation and existing continuation behavior, not real delivery,
screen-reader, held-VM or personal-device acceptance. Raw test logs and previews
remain under ignored test-results/approval-cards.

## October 26 actionable blockers and readable cards

Configuration requirements now supply compact repair actions for missing
platforms, destinations, recipient fields and declared committed-source needs.
Actions focus the specific control and matching proposal card without changing
selections or preparing work. Unknown source policy remains advisory. Runtime
blocked-step inspection opens a recorded failed prerequisite through intermediate
blocked steps, preserving the original plan and run.

Workflow maps retain native text scale as their zoom floor and scroll larger
graphs. Keyboard focus reveals cards; status changes preserve pan and manual
zoom. Wider cards, hover/focus feedback, chevrons and approval badges replace
repeated inspection guidance. Stage viewports ignore hidden-page height hints;
compact runtime context and subtask inspection keep repair controls visible at
1024×700 with 14-point text. Existing navigation cleanup remains intact.

Eight added contracts cover repair targeting and unchanged choices, source-policy
boundaries, recipient focus, wrapped/busy actions, readable zoom, keyboard
inspection, stable live views and failed-prerequisite navigation. These and the
existing footer, goal and summary contracts pass 30 native macOS Cocoa checks.
The final full portable run passes all 290 tests. An earlier attempt returned
awaiting-review in the existing continuation fixture; its isolated recheck and
the subsequent complete runs passed. No execution or approval policy was changed.
Synthetic 1280×800 and 1024×700 previews cover source/platform repairs, readable
destination cards, review, blocked delivery and its failure evidence. These are
portable presentation and native layout checks; real-provider, screen-reader,
held-VM and personal-device acceptance remain separate. Raw captures and all test
attempts remain in ignored test-results.

## October 26 toolbar, presets and visible choices

The header now keeps project selection, Project settings, More and Help. Checkout
paths remain in tooltips and disambiguate duplicate names. Presets live in Choose
work, load on deliberate selection and offer Save/Delete through a compact menu.
Visible exclusive goals and clickable source/platform/destination summaries share
the original request and invalidation paths. Tab counts and proposal warning icons
reflect active selections; dormant delivery choices remain preserved.

The focused UI suite passes 90 tests. Six new contracts cover header access and
duplicate names, keyboard goal selection, selection counts and conflicts, preset
save/load behavior, busy-state locking, project isolation and long labels at
1024×700 with 14-point text. These six and the seven earlier footer/attention
contracts also pass under native macOS Cocoa (13 checks). Synthetic native
previews verify configuration, delivery, modified presets, advanced operation and
the More menu. Existing persisted-device preset tests now exercise menu actions
and direct selection. No project planning, provider operation, device or VM is
used by the new fixtures.

The 277-test full portable run encountered one resource-wait event-order assertion
in the existing scheduler changes: the first contended resource was workspace
rather than the fixture's expected device. Its isolated recheck passes. Scheduler
code and that assertion were left unchanged by this UI pass. Raw attempts and
captures remain under ignored test-results.

## October 26 action hierarchy and attention

The first action-hierarchy pass adds a stage-specific footer docked below the
full window's workspace scrollbar, shared primary/secondary button presentation,
and direct failure/approval actions above the execution board. Seven added
contracts cover full-window footer bounds at 1280×800 and 1024×700 with 14-point
text, project-switch footer retirement, failure navigation with and without case
reports, mixed failure/approval states, unknown outcomes, reset and the unchanged
Cancel default and explicit selections in approval. The full portable suite passes
269 tests against the pinned commonUtils source. The focused UI suite passes 83
tests. All seven added contracts also pass using the native macOS Cocoa plugin.

Synthetic fixtures exercise layout and harmless presentation only. They do not
establish real-project delivery, provider, personal-device, VM or screen-reader
acceptance. Raw captures and logs remain in ignored test-results.

## October 26 mobile branch concurrency

The Logistics adapter removes its cross-platform admission barrier and generic
whole-run mobile-session reservation. Real harmless subprocess fixtures exercise
the resulting generated journey: independent Android/iOS contract steps overlap,
while their declared shared build resources remain exclusive. Manager fixtures
verify scoped cleanup progresses while another platform is active. Resource waits
include the named resource and capacity, appear distinctly in cards and subtask
details, and clear on process start without leaving a stale running clock.

The manager regression run passes 271 contracts; focused UI checks pass after
the final wording adjustment. Logistics passes 18 journey and 11 adapter contracts
using its isolated mobile interpreter against this checkout’s manager sources.
Adapter fixtures redirect generated settings into temporary directories. A native
macOS display-only fixture verifies the resource-wait presentation. No native
iOS/Android workloads, held VMs, physical devices or providers were exercised;
concurrent native acceptance remains a separate authorized check. Saved plans
retain their original dependencies and require fresh inspection to adopt the policy.

## October 26 desktop plan review

The [second-stage review brief](second-stage-ui-brief.md) now has a native Qt
summary implementation with familiar workflow cards and in-place subtask
inspection. All 262 portable contracts pass using the pinned commonUtils source
root and cover
captured values,
destination scoping, reviewed dispatch and dependent work, keyboard inspection,
stale Start rejection, independent blocked/approval branches, unknown-outcome
guidance, retained hydration and selection-independent case counts. Additional grouping
checks verify identical captured overview cards and arrows, shared task references,
headless imports, live updates while drilling into a card and reset after inspection.
Cross-platform order-only waits and platform cleanup remain nested without
expanding the overview into execution-level columns. Existing
review, cancellation, execution and history contracts remain green.

Synthetic macOS Cocoa windows were rendered and resized at 1280×800 and 1024×700,
including enlarged application text, exact-step inspection and a failed-run
summary. Back/Start stayed visible outside the summary scrollbar and the summary
had no horizontal scrollbar. Offscreen keyboard checks verify inspection without
starting commands. These fixtures establish desktop layout and portable behavior;
they do not establish native screen-reader, real-adapter release or provider
acceptance. No held VM, personal device, upload, publication or hosted dispatch
was used. Raw captures and all test attempts stay in ignored test-results.

The retained 52-step Logistics plan was also loaded read-only into an isolated
native macOS preview. Choose work and Review retain the same 19 cards, node
positions and arrows; all 52 tasks remain mapped, with 16 inside iOS. The plan
identity is unchanged. This checks the real large-plan shape that the earlier
small fixtures did not cover. It does not execute validation, access a VM/device,
or establish that the project's scheduling policy is optimal.

## October 25 refactoring follow-up

Manager runtime commit `bb34d5f` passes all 158 contracts on macOS and on the
dedicated Fedora 44 ARM64 and Windows 11 ARM64 guests. Windows uses x64 CPython
3.12.2 under emulation and retains three explicit POSIX-only skips. These are
native-platform process/Qt contracts with offscreen presentation; they do not
certify physical UI interaction or accessibility-reader behavior.

The guest plans also run Logistics' focused evidence-collection/cleanup fixtures,
collect the original manager result and logs, then remove their owned guest
workspaces. The existing public Windows tool cache is intentionally retained.
Both real backend flows pass. Tests cover responsive background artifact checks,
cancelled/stale review, changed files during the approval dialog and refusal to
launch an external effect. Those fixtures use harmless processes, with no upload
or publication. The exact reviewed manager/commonUtils pins are recorded by each
retained run; owning project source can still be a labelled development snapshot.

Generic contracts exercise real subprocess/GUI chains, failure, timeout,
cancellation with descendants, cleanup, locking, redaction, isolated adapters,
settings migration, workflow restart, exact artifact review, partial provider
outcomes and resource contention between two manager processes. Controlled
transports cover accepted requests followed by connection loss without duplicates.
These checks do not establish unavailable native-platform or publication coverage.

macOS acceptance includes real launcher startup from another directory and a
checkout path with spaces/Unicode, an actual Logistics adapter plan through the
external engine and Qt route, and an inert APK installed in an owned disposable
Android emulator with verified cleanup. Current source/dependency identities and
actual outcomes belong to each ignored run report, not to historical green claims.

Dedicated Fedora and Windows ARM64 guests provide native launcher, process-tree,
locking, atomic-state, Unicode-path and cleanup acceptance. Their isolated Python
3.12.2 environments run the same pinned manager/commonUtils sources. Windows uses
native junction fixtures without Developer Mode or symlink privilege changes;
POSIX signal-only cases remain explicit skips, alongside Windows process-job checks.
Project filesystem suites may additionally require actual Windows symbolic links.
The dedicated VM setup supports explicitly approved Developer Mode and preserves
that approval across recreation, as described in [VM setup](../user/virtual-machines.md).
Its normal-user symlink probe is separate from completing the project's suite.
Report publication retries transient Windows sharing conflicts for at most two
seconds, and closing a project panel cancels/drains its history reader before
releasing project files. Raw attempts and corrections remain in ignored evidence.

Linux/Windows Android testing is intentionally unavailable in this release,
including on x64. Its remaining implementation and native validation are recorded
as known limitations and deferred to separate Windows and Linux follow-ups.
Existing ARM64 guests must not be presented as Android passes. See [dedicated test machines](../user/virtual-machines.md).
The held Fedora guest and Windows Testbed are not substitutes.
Blue Hole requires a supported Blender 5.2.2 isolated enable/import smoke test;
portable tests and an inspected ZIP do not replace that gate. Missing environments
keep the applicable follow-up acceptance open. No push, live hosted
dispatch, tester notification or release upload is used to manufacture evidence.

Project source, packaging, release gates and native suite policy remain in the
owning repositories. Passing tests never publishes. App Store/Google Play remain
unimplemented. No manager self-release/self-update pipeline, visual workflow editor,
credential sync or new remote-agent service is part of this implementation.

## Guided UI validation and adoption boundary

The [twelve implementation briefs](ui-improvement-plan.md) now have manager-side
support for staged configuration/review, suite selection, preseeded step status,
independent live clocks, JUnit case evidence, filtering and failure detail, direct
retained delivery review, background history, and accumulated attempt timing.
Portable tests use real harmless Qt-to-CLI subprocesses to exercise failure gates,
case reports on nonzero exit, exact suite forwarding, stale selections, declined
approval, changed artifacts, unknown outcomes, recovery and read-only history.
Offscreen Qt screenshots cover configure, review, mixed results and compact sizing;
raw captures and test output belong under ignored test-results.

Briefs 1–11 are implemented in this repository. Brief 12 now has source adoption
in Logistics and Blue Hole: descriptor catalogs, matching suite routing, JUnit
emission, complete release-gate inventories, exact-package Blender acceptance and
separately reviewed deliveries. Real registered-adapter portable runs verify case
capture through project-owned commands and interpreters. Controlled tests cover
missing native hosts, source/package mismatch, required skips, incomplete device
families, and interrupted distribution attempts.

Real Blender acceptance uses an explicitly selected supported 5.2.2 runtime and
the exact prepared ZIP in an isolated profile. Runtime availability alone does
not satisfy that gate. Native mobile acceptance and exact-source hosted receipts are separate
requirements; an absent iOS runtime receipt blocks reviewed TestFlight delivery.
Owning dependency pins select a locally reviewed manager commit containing reporting;
that commit and its commonUtils pin must be available remotely before fresh hosted
setup can use them. Local pinning does not push those commits. No hosted action, release, personal-device
installation or tester upload was used to manufacture acceptance. Offscreen UI
checks do not prove native OS interaction or accessibility-reader behavior.

## Android host preflight

Host capabilities distinguish the emulator executable's supported host architecture
from its selected Android image ABI. Linux/Windows hosts report
Unavailable before SDK commands or workspace creation, including when project
configuration claims readiness. A separately declared hosted option remains visible.
The dedicated VM readiness view uses the guest's actual architecture for this check.
See [host requirements](../user/hosts.md#android-emulator-host-architecture). Current implementation briefs close with this explicitly deferred scope; the
platform follow-ups require real Android acceptance before enabling x64 support.

## Logistics native desktop acceptance — 2026-10-25

The dedicated Fedora 44 ARM64 and Windows 11 ARM64 guests completed the declared
Logistics platform checks. Windows uses x64 CPython 3.12.2 under emulation; Fedora
uses native ARM64 CPython 3.12.2. Both use Qt 6.12. This establishes the selected
guest coverage, independently of physical x64 hardware or fresh Ubuntu acceptance.

Failed full attempts remain preserved. Their unchanged shared, compression and
packaging results were reused after checking dependency, suite and package inputs.
At Logistics `14e9c13c` / commonUtils `b105857d`, all 117 cases in the 12 corrected
or affected application modules passed on each guest. The current manager
`798587b` passed 154 native contracts on Fedora and Windows; Windows reports three
explicit POSIX-only skips. Actual guest probes also verified recovery of exits 0
and 7 after transport loss, no duplicate execution, and cancellation before child
admission. The final ordinary Logistics backend runs passed setup, focused tests,
report retrieval and owned cleanup (Windows `12cc9598`, Fedora `14e9c13c`).

| Verified check | Windows seconds | Fedora seconds |
| --- | ---: | ---: |
| Shared suite, unchanged pinned inputs | 599.92 | 128.40 |
| Compression parity | 31.06 | 4.67 |
| Release/package checks | 23.50 | 1.48 |
| Current manager contracts, 154 cases | 65.32 | 14.55 |
| Final focused backend flow, including setup/transfer/collection | 68.02 | 39.41 |

Windows packaging includes actual extracted batch-launcher execution and CRLF
checks. Fixes cover large-plan stdin transfer, explicit Qt widget ownership,
read-only Git scratch cleanup, original ZIP entry validation, portable fixtures,
asynchronous reader teardown and durable Windows invocation receipts. Evidence
transfer archives are removed after verified host collection. Raw attempts,
per-case timings and cleanup proofs stay under ignored `test-results/logistics-native/`.
Later source changes retain their own acceptance requirements. Android x64 and
post-GitHub integration remain separate follow-ups; no push or hosted dispatch
was used for this local acceptance.

## Final artifact-hash cancellation check

Runtime `9225924` passes 159 contracts on macOS and both dedicated guests.
Fedora completes the suite without skips; Windows retains its three POSIX-only
skips. The additional case cancels while hashing a prepared artifact and requires
a serialized cancelled result plus successful owned cleanup. The real guest
plans also pass their focused Logistics result-lifecycle checks, retrieve evidence
and remove their owned workspaces. No upload or personal-device action occurs.

## Settings and goal-based workflows — 2026-10-26

The manager's portable suite passes 178 tests on macOS using its existing
`.venv`, `QT_QPA_PLATFORM=offscreen`, and the pinned real commonUtils submodule.
Coverage includes Settings load/save responsiveness, cancellation/timeouts,
malformed/empty/error states, retained failed edits, explicit discard, credential
rejection and the distinction between interpreter and protected credential paths.
Legacy plan hashes are unchanged when journey evidence is absent.

Journey schema 1 coverage uses harmless temporary adapters and commands through
both the real isolated bridge/CLI and GUI-to-CLI pause/resume. It verifies exact
platform/destination intent, all-platform gates, overlapping independent approved
branches, per-action approval selection, shared retained preparation, partial
success, unknown-outcome reconciliation and no duplicate effects. The fixture
includes GitHub, Firebase, TestFlight and device-install effect types; these names
represent harmless commands, not actual provider or device acceptance.

Offscreen 1280×800 configuration/review and Settings images were inspected. Raw
screenshots and logs remain under ignored test-results/ux-audit. Native window
activation, assistive technology, high-DPI behavior and non-technical user sessions
remain acceptance work. The original Settings symptom was not reproduced in the
real project window; its synchronous pre-display loading path has been removed.

At completion of the initial manager work, Logistics had not yet adopted journey
schema 1. The subsequent explicitly requested integration adds its project-owned
`journey_plan` adapter, immutable shared source/settings capture, scoped cleanup,
all-platform gates and the existing GitHub/Firebase/TestFlight delivery policy.
The actual registered descriptor renders five platforms and three destinations
in the offscreen UI. The subsequent registration-based authorization change allows descriptor updates
without a separate trust prompt, while retaining validation and identity checks. No VM, device, provider or
credential file was changed. No publish, push, hosted dispatch or native
deployment was performed. A tracked manager-source
scan found no known token or private-key material, excluding synthetic test
fixtures and the pinned submodule; credential rejection tests provide additional
coverage and are not a claim that arbitrary trusted project output is sandboxed.

The follow-up adapter integration passes 180 manager portable tests and 46 focused
Logistics snapshot/adapter/suite/settings tests in their respective existing
environments. Explicit per-host journey mappings retain unavailable selections
without hosted fallback. Direct Settings editors and isolated bridge writers
share the credential/reference guard. The published Logistics manager pin remains
unchanged; older manager installations retain single-platform API-1 operations
and require an explicit reviewed local upgrade to use combined journeys.
