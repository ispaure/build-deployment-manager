# Integrated validation and delivery contract

Journey schema 1 is an optional extension of the schema-1 descriptor and isolated
bridge. It provides one project-owned planning request for several platforms and
destinations. Legacy `plan` requests and plan identities remain unchanged when
journey evidence is absent. Metadata inspection and validation remain headless.

## Descriptor

Add `journey` alongside existing `capabilities`, presets and suites:

```json
{
  "journey": {
    "schema": 1,
    "selectable_backends": true,
    "platforms": {
      "android": {"label": "Android", "operation": "Test", "backend": "Local"},
      "ios": {"label": "iOS", "operation": "Test", "backend": "Local"}
    },
    "destinations": {
      "github": {"label": "GitHub release", "platforms": ["android", "ios"]},
      "firebase": {"label": "Firebase testers", "platforms": ["android"]},
      "testflight": {"label": "TestFlight", "platforms": ["ios"]},
      "devices": {"label": "Install on selected test devices", "platforms": ["android", "ios"]}
    }
  }
}
```

Platform/destination IDs use letters, digits, underscores, dots or hyphens.
Operations must exist in the existing platform capabilities; configured backends
must be available through the existing host backend contract before planning.
Labels and optional destination descriptions are presentation only. Each
destination lists all platforms it needs. This example does not supply provider
commands; the owning project must implement its real supported combinations. A
project can declare Firebase on iOS if its adapter actually supports that path.
Platform rows can include `backends_by_host`, mapping `darwin`, `linux` or
`win32` to explicit backend labels. The bridge and directly embedded adapters
use `journeys.for_host` to resolve those declarations. An absent mapping retains
the declared default; it never substitutes a hosted backend.

## One planning request

The trusted bridge receives action `journey_plan`, with `values.intent`:

```json
{
  "schema": 1,
  "goal": "deliver",
  "platforms": ["android", "ios"],
  "destinations": ["github", "firebase", "testflight", "devices"]
}
```

Goal `validate` requires no destinations; `deliver` requires at least one.
Empty/duplicate/unsupported selections and missing destination platforms fail
before project code runs. `revision`, `pattern`, `build_override` and `release_tag`
are supplied alongside intent. The project owns full release validation; focused
checks must not bypass required gates.

Return the ordinary schema-1 response containing one `Plan`. Capture a consistent
source/settings context, allocate versions under project policy and declare each
artifact builder once. Never concatenate independently prepared platform plans
and assume snapshots, counters, resource ownership or identities agree.

## Plan evidence and gates

Add `journey` metadata to the plan, referencing its actual phase IDs:

```json
{
  "schema": 1,
  "goal": "deliver",
  "platforms": {"android": ["android-tests"], "ios": ["ios-tests"]},
  "destinations": {
    "github": {"identity": "GitHub owner/repository, release v1.2.3", "steps": ["publish-release"]},
    "firebase": {"identity": "Firebase app-id, internal-testers", "steps": ["upload-firebase"]},
    "testflight": {"identity": "App Store Connect app-id, build 123", "steps": ["upload-testflight"]},
    "devices": {"identity": "Explicit authorized device IDs", "steps": ["install-android", "install-ios"]}
  }
}
```

The manager checks exact goal/platform/destination agreement with intent. Each
platform needs required, non-cleanup `kind=test` phases. Every delivery step must
belong to exactly one selected destination, use an explicit upload/deploy/publish
effect, be required, and depend transitively on its destination’s required platform gates.
This version implements a common validation barrier; independent-platform release
policy requires a future explicit contract. Unselected effects are rejected.

Phases retain real dependencies, artifacts/types, timeouts, resource claims and
effects. Use `max_workers` and capacities for overlap. Required preparation,
signing and identity checks must also be dependencies of their consumers. Exact
destination identity must identify recipients, assets and device IDs sufficiently
for approval. Never include credential contents. Keep source/artifact policy in
the owning project, not in manager-specific commands.

Ready external steps pause for review. Grouped review creates distinct approvals
for selected eligible steps; unselected steps remain pending. Later-dependent
effects need review after their prerequisites exist. Approvals stay session-only
and artifact-bound. Passed preparation is reused after checksum checks. Unknown
external outcomes require reconciliation; another branch can retain its success.

## Headless planning

```sh
build-manager journey --project REGISTRATION --goal deliver \
  --platform android --platform ios \
  --destination github --destination firebase --destination testflight \
  --release-tag v1.2.3 --output /private/run-plan.json
```

Planning does not execute returned phase commands, although trusted preparation
can create source snapshots. Use the existing runner/resume approval mechanisms.
GUI and CLI use the declared project interpreter, never importing project code
or finding sibling checkouts.

## Settings and credentials

The editor uses cancellable `load_settings`/`store_settings` helpers with bounded
30-second requests; all widget work stays on the GUI thread. Before forwarding
`save_settings`, the manager checks declared editable fields and reference paths.
Adapters retain storage ownership. Private profiles belong outside tracked source.
Credential material belongs in protected files/helpers or inherited environment.
Do not return it in settings, plans, logs or artifacts.

Known credential formats, sensitive field names, inherited credential values and
private-key material are rejected before profile/plan writes. New protected-file
references must resolve outside Git checkouts, even ignored paths. Existing
references are preserved while editing unrelated fields; saving does not move
or copy credential files. Direct editors and bridge writers share this guard. Private account
and registration defaults live in the OS application-config directory. These
checks provide defense in depth; trusted adapter code remains outside a sandbox.

## Adoption and verification

Portable tests cover isolated intent forwarding, gate enforcement, approval,
overlap, retained preparation, partial/unknown outcomes, GUI-to-CLI continuation,
settings cancellation and credential rejection using temporary harmless projects.
Owning projects must implement `journey_plan` and prove actual source/artifact/
recipient identity and provider receipts with explicitly authorized fixtures.
Existing projects are not silently upgraded by this manager extension.
Logistics now implements this contract in its owning repository, including a
shared source/settings capture and the existing native release gates. See its
`docs/development/build-manager-journeys.md` for usage and remaining native acceptance.

- [Adapter contract](adapters.md)
- [Guided UI](../user/guided-ui.md)
- [Workflow review and recovery](../user/workflows.md)
- [Documentation home](../docs.md)

## Explicit execution and one-run values

An adapter opting into `journey.selectable_backends` receives intent `backends`,
a complete selected-platform-to-backend mapping validated against its declared
backend options. Older adapters retain their declared defaults. A hosted test
launch uses explicit phase effect `dispatch`, never `publish`. Plan
`journey.executions` maps each platform to `{backend, steps}`; each dispatch must
belong to exactly one platform and precede all its required test gates. It must
be required and cannot be cleanup. All dispatches require ordinary artifact-bound,
session-only external approval, persisted intent and unknown-outcome reconciliation.
Checks-only journeys permit these reviewed launches without any delivery effects.

Optional descriptor `run_fields` declares unique `id`, `label`, `kind` (`text` or
`multiline`), and optional `operations` and `destinations` applicability lists.
`run_defaults` returns declared default values; `run_overrides` carries only declared
text fields into planning. Credential material and oversized values are rejected.
The owning adapter must capture effective settings immutably and record overrides
in source evidence; neither preview nor execution writes them into saved defaults.
Late default loading preserves edited fields and invalidates any earlier review.

CLI examples add `--execution ios=GitHub` and
`--run-value 'testflight.what_to_test=Try the updated editor'` to a journey request.
Unspecified selected hosts use declared defaults. These commands prepare plans;
they do not authorize dispatch or publication.

## Independent destination gates and completion order

Each destination evidence row can declare `platforms`, a nonempty subset of the
selected platforms. Every external step must depend on all required gates for
that destination, plus its prepared artifact. Intent also carries the descriptor's
`destination_platforms`; returned evidence cannot narrow that declared requirement.
Legacy rows without a scope conservatively require all selected platforms.
Firebase requires Android, TestFlight iOS; a project's GitHub release can require
multiple desktop platforms. Unrelated failure does not block a passing destination.

Phase `waits_for` is optional completion order. These edges are included in the
scheduler and dotted in the diagram, but do not count as successful validation or
artifact ancestors. Use them for admission after another branch has released its
resources; downstream tests must still be ordinary required success gates.
Empty `waits_for` is omitted from serialization to preserve legacy plan identity.
The diagram centers each depth row and orders children by their parents' positions.
A shared resource may serialize native work even when delivery branches are
independent. Prepared external actions retain the existing explicit review pause.

Optional `unavailable_destinations` lists `{label, reason}` rows. Configuration
shows these as explanations, never selectable executable destinations. Projects
should explain absent artifact/review contracts without implying device discovery
or delivery support.

## Grouped destinations and explicit recipients

Destination metadata may declare a display `category` and a `recipient_field`.
The latter names a `run_fields` entry with kind `multiselect` applicable to that
destination. Values remain text in the API: a JSON array of up to 50 distinct
stable IDs. The GUI offers checkboxes and explicit ID entry, never automatic
selection. Adapters validate IDs and capture the actual target mapping in their
source/recipe evidence. IDs cannot become shell strings.

Adapters declaring `dynamic_run_inputs: true` provide `run_defaults`; multiselect
adapters provide `run_choices`, returning `{field_id: [{id, label}]}`. Both actions
run asynchronously in the trusted project interpreter. They must be read-only;
Logistics returns saved metadata without native discovery or device connections.
Reload preserves selected IDs, including entered recipients absent from a refreshed
list. Failures allow explicit ID entry and do not silently broaden recipients.
External installation steps declare effect `deploy` and require ordinary exact-
artifact review, destination validation gates and unknown-outcome reconciliation.

## Package cards and source requirements

A journey may declare an ordered `packages` mapping for its non-executable
configuration overview. Each entry has a `label`, optional `description`, a
`stage` (`build` or `package`), required `platforms` and optional `dependencies`
referencing earlier package IDs. A destination's `package` references its final
package. Shared IDs appear once with branches to their consumers. Packages never
create executable commands; the project must return the matching actual phases.
Legacy descriptors retain a generic preparation card until Review.

For selectable variants, a destination may declare `package_field`,
`package_default` and `package_variants` mapping option IDs to package IDs. The
field must be a declared run input with kind `choice`, matching `default`,
`options` (ID-to-label mapping) and destination applicability. The selected ID is
forwarded as a text run override and retained like other run choices. Distinct
Debug and Release package IDs prevent the overview from implying false reuse.

Destinations and packages may declare `source_policy`: `captured` (default),
`committed`, or `clean-checkout`. The overview explains selected requirements
before preparation. The project adapter remains responsible for enforcement;
metadata neither commits changes nor authorizes publication.

Executable phases can provide optional `label`, `description`, and `section`
(`source`, `platforms`, `delivery`) for readable cards and grouped headings.
Empty metadata is omitted from serialization to preserve legacy plan identities.
The map reads left to right; sibling order follows the adapter's dependencies,
and later columns stay near their parents. These positions do not alter scheduling.
