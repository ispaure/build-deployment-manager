# Guided testing and delivery implementation plan

## Outcome and ownership

Make one session take a user from choosing a project and goal through inspecting
source, running gates, reviewing prepared outputs, and continuing to the declared
GitHub or mobile destination. The manager supplies presentation and orchestration;
Logistics and Blue Hole supply executable suites, source snapshots, release rules,
destinations and storage. A passing test is never authorization to publish.

This is a set of implementation briefs, each with a concrete acceptance contract.
Portable verification uses temporary projects and harmless processes. Native
acceptance and adoption in the two owning repositories are separate work: no
unavailable host, held VM, personal device or live provider is a test fixture.

## Brief 1 — Navigation and first-run guidance

Replace the single dense presentation with named stages: Configure, Review,
Run and results, History. Keep the primary action near the stage it advances.
Explain the next action in ordinary language. Retain project selection and trust
at window level; never run an untrusted adapter to populate presentation.
Acceptance: a new user can identify where to choose work, inspect it and run it;
the window remains usable at laptop sizes and with keyboard navigation.

## Brief 2 — Goal selection and progressive disclosure

Prefer project-declared workflow presets, then platform, operation and backend.
Offer named test suites when the descriptor declares them. Put source revision,
focused patterns, build overrides and release tags in an expandable advanced
section. A selection change invalidates the reviewed plan immediately. Preserve
custom operation and older adapters. Never infer a deployment command from a label.
Acceptance: preset and suite selection reach the isolated bridge exactly;
unsupported choices stop before execution and cannot reuse an old review.

## Brief 3 — Human-readable plan review

Show operation, backend, source identity, declared destination, settings and all
ordered steps. Show dependencies, required/optional gates, effect and timeout in
step details. Keep complete redacted JSON available for detailed inspection.
Acceptance: every planned step is visible before execution; external steps are
explicitly marked for review. No credential contents appear in summaries or logs.

## Brief 4 — Complete execution board and timing

Seed all steps as queued; update running, waiting, passed, failed, timeout,
cancelled, skipped, unknown and awaiting-review states. Show elapsed time per
running step and final measured duration per completed step. Show overall progress
without describing skipped or failed gates as successful. Keep parallel steps
independent and display dependency/resource waiting reasons.
Acceptance: queued steps never disappear, concurrent clocks advance independently,
and report hydration restores completed state after resume or history selection.

## Brief 5 — Individual test results

Support explicitly typed JUnit XML artifacts from project runners. Normalize case
identity, suite, status, seconds and failure/skip message without importing project
code or adding a runner dependency. Retain reports on test failure as well as
success. Treat malformed declared reports and reported failures as failed gates;
missing mandatory reports cannot produce success. Bound parsing and reject XML
entities/DTDs. Do not invent case results from console text.
Acceptance: passed/failed/error/skipped cases, Unicode, nested suites, malformed
reports, nonzero exits and redaction have portable coverage. Distinguish phase
progress from case counts; case results appear when their report is captured.

## Brief 6 — Useful results and failure investigation

Show individual cases with status and timing, searchable by suite/name/message
and filterable to problems. Selecting a step explains its dependencies, current
reason, outcome, artifacts and log location. Keep live output available in its own
tab. Provide a direct route to retained evidence without silently opening provider
URLs or executing commands embedded in reports.
Acceptance: a failed case can be found without reading the entire JSON document;
results stay attached to the run that produced them.

## Brief 7 — Review and continue in the same workflow

When preparation ends awaiting review, expose a direct continuation action on the
current run. Present the original source/settings, artifacts and destination,
revalidate checksums, then obtain explicit effect approval. Reuse passed work only
through existing recovery rules. Never repeat an unknown external outcome.
Acceptance: a harmless two-stage fixture pauses, continues in the same result
directory, reuses the preparation and blocks changed evidence. Keep manual resume
for older results and interrupted work.

## Brief 8 — Project-owned run history

List recent retained result reports in the selected project's results directory,
including date, goal, outcome and duration. Opening one is read-only and hydrates
the same board and test view. Continuation is a separate action through recovery.
Tolerate incomplete/corrupt entries and avoid recursively scanning build caches.
Acceptance: project histories do not mix; corrupt history does not break startup;
viewing an old result never enables a new run using stale selections.

## Brief 9 — Shared suite organization and adapter contract

Publish [the test organization contract](test-organization.md) for Logistics and
Blue Hole. Validate optional suite metadata during descriptor inspection. Stable
IDs, declared target/operation applicability, and an explicit suite bridge value
allow a common chooser without manager-owned project paths or dependencies.
Acceptance: legacy descriptors remain valid; duplicate IDs, unknown targets and
malformed metadata fail before trust/execution. Each project owns migration and
must prove suite selection is honored rather than silently running another suite.

## Brief 10 — Accessibility and state integrity

Use text states, descriptive accessible names, resizable tables and ordinary Qt
controls. No color-only status. Disable conflicting actions during preparation
and execution; retain cancellation and owned cleanup. Clear stale results when
starting another run and distinguish history viewing from plan preparation.
Acceptance: keyboard use, stale review rejection, launch failures, cancellation,
and inspection errors have explicit visible outcomes.

## Brief 11 — Regression and visual verification

Exercise real Qt-to-CLI workflows with temporary projects, including mixed test
outcomes and pause/resume. Run the portable manager suite against the pinned real
commonUtils checkout. Capture representative GUI screenshots under ignored
test-results and inspect sizing and information hierarchy. Keep native release
acceptance separate from these checks.
Acceptance: changed contracts pass, headless imports remain Qt/project-free,
submodule pins remain untouched, and no external delivery is used as evidence.

## Brief 12 — Adoption and remaining native acceptance

Logistics: declare portable, desktop UI, native Android/iOS and release gates;
prepare artifacts once, then declare separately reviewed GitHub/tester/device
effects with complete dependencies. Blue Hole: declare portable tests, supported
Blender integration, package inspection and install/enable acceptance; keep the
Blender interpreter and version gate project-owned. Both must emit JUnit reports
for case visibility and use explicit native skips/failures for unavailable hosts.
Acceptance requires changes and tests in their owning repositories and authorized
native fixtures. The manager cannot claim project adoption by documenting it.

## Delivery sequence and exclusions

Implement 9 and 5 as independent headless contracts, then 1–4 and 6, then 7–8,
followed by 10–11. Brief 12 is a published integration requirement; adoption
now has local source implementation in both owning repositories. Recorded local
acceptance includes exact-package Blender 5.2.2 and Logistics Android/iOS native
and core-runtime checks at their retained source identities. Future delivery still
requires matching exact-source gates and hosted receipts; those local results do
not certify newer application changes. Windows/Linux x64 Android remains deferred
to the separate original-series follow-ups 11/12. The numbering in this UI plan
is independent of that original Obsidian brief series.
Owning projects explicitly pin the reviewed manager implementation; the commits
must be available remotely before hosted setup can consume those pins. Existing generic transports remain the route
to GitHub and mobile. This work adds no App Store/Play submission, automatic push,
provider credentials, arbitrary workflow command editor or personal-device action.
Record completed work and remaining acceptance in [validation](validation.md).
