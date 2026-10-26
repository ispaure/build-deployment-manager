# UX redesign: implementation audit and second pass

## Native operator walkthrough — 2026-10-26

The whole-app pass adds a visible project-add action and descriptor preview,
automatic selection of the added checkout, an explicit setup panel, searchable
settings with optional value origins, visible plan steps and plain effect labels,
platform/source review context, clearer Start actions and contextual run controls.
Inactive project actions and unsupported storage cleanup are disabled. Empty
history and unknown external outcomes explain the next safe action.

Settings workers capture plain project data rather than dialog widgets. Closed
dialogs use Qt-owned deletion, the main window closes/drains its panel, and result
navigation uses bound slots. These changes address the shutdown/garbage-collection
crashes found during regression work. All 196 manager contracts passed after the
final corrections; initial failures and corrected attempts remain retained.

The real native macOS Cocoa window was driven with Qt input events on attached
displays, using the actual Logistics and Blue Hole descriptors, interpreters and
adapter subprocesses. This was additional acceptance beyond fixture rendering:

- Add/select projects, inspect their preview and switch between them.
- Load all 63 Logistics settings, search categories, edit/save through the real
  bridge and reopen the form using an isolated project profile. Original profile
  bytes remained unchanged. Application appearance saved to an isolated registry.
- Prepare a real invalid-pattern request and inspect its visible error. Preserve
  Logistics' refusal to snapshot a dirty shared dependency; explicitly select
  committed source instead of altering unrelated work or weakening the guard.
- Review and explicitly start focused Logistics checks at `2ff0e581`; all seven
  cases and the environment phase passed. This is focused UI-to-run acceptance,
  not certification of the current dirty application tree or a full native suite.
- Review/start Blue Hole's actual portable suite at `b709b4c`; all 63 cases passed.
  Inspect its reported tests/timing, cancel a separate owned run and view the
  successful saved result read-only. No Blender or release acceptance is inferred.
- Inspect final native settings/review/results and compact layouts. The actual
  macOS launcher also completed its harmless startup/close route.

Raw screenshots, source/dependency identities, reports and failed attempts remain
under ignored `test-results/full-app-usability`. No held VM, personal device,
publication, upload or hosted dispatch was used. Native screen-reader acceptance,
occasional-user studies and new Linux/Windows GUI coverage remain separate; the
historical sections below describe the earlier audit rather than these results.

The [redesign brief](ux-redesign-brief.md) was only partially implemented by the
first pass. Renaming tabs did not give occasional users a reliable sequence, and
an untrusted project adapter could leave settings looking like an empty editor.
This audit describes the implemented behavior and remaining acceptance work.

## Implemented in the second pass

| Brief requirement | Current behavior |
| --- | --- |
| Guided sequence | Choose work → Next: review plan → explicit Start → Run & results. Back returns to choices. Future workflow pages have no clickable tabs. |
| Separate retained history | Past runs is separate navigation; opened results retain their original source and plan. Run & results becomes available once results have been initialized. |
| Plain review | Source, platforms, host, delivery order and exact declared destinations appear before Start. Technical dependencies and complete plan are hidden until requested. |
| Explain actions | Step guidance, inline destination requirements, field descriptions and Start explanations replace tooltip-only instructions. Test-only selection hides delivery inputs and release identifiers. |
| Distinct settings | App settings is visible in the standalone window and embedded panel. It controls text size and explains the workflow and project settings scope. Project settings remains a separate button. |
| Settings load and recovery | The shell appears before asynchronous loading. Failures show status and retry. The blank form is hidden on load failure. |
| Project registration | Adding a checkout authorizes its adapter without a trust dialog. Existing registrations and descriptor updates retain access; descriptor validation and project identity checks still apply. |
| Results and profiling | Results summarizes reported case counts and next actions; Tests exposes search, filters and failure detail; Timing lists measured cases slowest first, with total, mean and median durations. Missing durations are explicit. Step details and live logs remain available. |
| Honest measurements | Counts come from captured case reports. No reports means unavailable case counts. Summed case time is distinguished from active run time and parallel overlap. |

## Existing contracts retained

Multi-platform validation and coordinated delivery use the project-declared
journey contract, including Logistics. All required selected-platform gates block
delivery. Prepared files and exact destinations need separate explicit approval.
Independent approved branches can overlap; partial successes remain visible.
Physical-device install workflows remain separate until the project supplies a
safe prepared-artifact delivery contract.

Credential contents are rejected from manager settings, plans and profiles. New
protected-file references must point outside Git checkouts. App appearance lives
in the manager's private configuration directory; project settings remain owned
by each adapter. No trust registration or credentials were changed for the user
during this audit, and no delivery was performed.

## Verification and remaining acceptance

Portable Qt tests exercise Back/Next navigation, retained reports, measured timing,
profile saving and applying, and a real isolated fixture bridge that loads settings without approval for both new
and legacy registrations. Registry regressions cover descriptor updates, moved
checkouts and changed project identities.
Existing execution, recovery, credential and journey tests remain required.

The actual Logistics settings bridge was read successfully and returned 63 fields.
The registered checkout was untrusted after descriptor changes; that was the
verified settings blocker. Registration-based authorization now removes that blocker. Offscreen screenshots cover the actual registered choices
and trust blocker, plus synthetic review, result and timing states. Raw evidence
is retained only under ignored `test-results/ux-audit`.

Native macOS keyboard/screen-reader acceptance, usability sessions with occasional
release users, and native multi-platform/provider acceptance remain outstanding.
Portable tests and offscreen screenshots do not establish those outcomes. The
app still uses native Qt controls; this pass changes navigation, explanations and
results, rather than replacing the toolkit.

## Run configuration follow-up — 2026-10-26

Consolidated settings into one toolbar entry and flattened configuration into the
window scrollbar. Opted-in adapters expose execution location per platform.
Project-declared run notes and recipient groups are captured separately from saved
defaults and shown during review. Release adapters supply automatic names when the
optional advanced override is blank. Hosted validation has a separate reviewed
`dispatch` effect with reconciliation, rather than masquerading as publication.

Native Cocoa testing uses the actual Logistics adapter: short-window navigation,
hosted macOS/iOS plan review, TestFlight notes capture and automatic release naming.
Hosted and release plans are inspected without starting their external actions.
Portable tests additionally exercise approval, unknown outcomes and stale reviews.
Evidence remains in ignored test-results; native provider acceptance is not inferred
from plan previews.
