# Project test organization contract

Logistics and Blue Hole own their suites and must expose the same manager-facing
contract. The manager never imports their test modules, searches sibling checkouts,
installs project dependencies or decides release eligibility.

## Layout and suite identity

Use a project-owned test root with `unit`, `contracts`, `integration`, `ui`,
`native` and `acceptance` groups (existing roots may map into these groups).
Fixtures belong alongside the narrowest owning group. Keep raw reports, logs,
screenshots and temporary packages in ignored project test-results storage.
Use stable suite IDs such as `portable.contracts`, `desktop.ui`, `android.native`,
`ios.native`, `blender.integration` and `release.acceptance`. Case IDs come from
JUnit classname/name; parameterized cases need distinct names. A suite ID cannot
change meaning between targets or releases. Unit tests are fast isolated checks;
contracts validate boundaries; integration uses real dependencies; UI exercises
interactions; native requires the actual runtime; acceptance proves the packaged
product. Portable coverage does not substitute for native acceptance.

## Descriptor and selection

Optional `test_suites` in build-project.json is a list of objects:

```json
{
  "id": "portable.contracts",
  "label": "Portable contracts",
  "description": "Boundary checks using temporary local fixtures",
  "tier": "contracts",
  "platforms": ["macOS"],
  "operations": ["Test"]
}
```

Platforms/operations must be declared capabilities. Allowed tiers are `unit`,
`contracts`, `integration`, `ui`, `native`, `acceptance`. The bridge receives
`values.suite` only when a suite is selected. It must reject unknown/inapplicable
IDs and combine any focused pattern within that suite, never broaden it silently.
No suite selected preserves the adapter's full declared-suite behavior. Old
descriptors remain supported. Presets may declare a `suite` ID as well as platform,
operation and backend. A descriptor change requires renewed trust.

## Plans and evidence

Declare independently actionable suites as stable Phase IDs, with `kind='test'`,
bounded timeout, explicit prerequisites, required status, isolated project command,
working directory and owned resources. Cleanup uses existing `always` semantics.
Declare each report in `artifacts` and mark its exact path in `artifact_types` as
`junit`. Emit standard `testsuite`/`testsuites` XML with testcase name, classname,
time in seconds when actually measured and failure/error/skipped child elements.
Omit time when the owning runner supplies no case duration; the UI displays an
unknown duration rather than inventing one. Use a fresh report path
per source/suite execution and remove stale outputs before a retry. Reports must
be written even when the runner exits nonzero. Each report must contain actual testcases;
an empty suite is not evidence that tests passed. The manager displays cases when
the phase finishes; console output remains live. Do not emit private credentials
or customer data in reports. Retained original artifacts remain subject to the
existing checksum and retention rules.

Runner exit failure, reported failure/error, a missing report on successful exit,
or an invalid report fails the gate. Skipped cases remain visible and never count
as passed cases; projects must make required native coverage a failing release gate
when skipped. The manager does not infer required case policy from report labels.
Declare an explicit release acceptance phase that checks the project's expected
suite/case inventory, native host identity and allowed skip policy.

## Delivery dependencies

One project preset may prepare source → run required suites → build → verify
package → await destination review → upload/deploy/publish → cleanup. Every
external phase must depend on all required gates and the exact artifact preparation.
Declare effect per external phase and explicit harmless effects on preparation.
Include source fingerprint, toolchain/runtime versions, actual package identity,
version and destination in plan/source/settings and prepared evidence. Preserve
destination-specific receipts and reconcile unknown provider outcomes before retry.
GitHub release and mobile deployment are separate destinations even in one sweep.

## Required adoption checklist

Logistics maps mobile, desktop and release checks into these groups using its own
interpreter and source snapshots. Blue Hole maps pure-Python contracts and Blender
integration/packaging/enable checks using its own supported Blender runtime. Each
project adds tests for descriptor selection, exact suite forwarding, JUnit output
on failure, unavailable-native-host behavior, release gate completeness and
effect dependencies. Neither project can satisfy this contract solely by adding
suite labels. Native install/deploy validation needs authorized disposable targets;
publication/dispatch is a separately authorized acceptance action.

## Reporting helpers and current adoption

The headless `build_manager.reporting` module provides `write_junit(path, suite,
cases)`, `JUnitResult` and `run_suite(suite, output, name, fail_on_skip=True)` for
project-owned runners. Cases use name, classname, status (passed/failed/error/
skipped), optional seconds and message. The writer filters XML control bytes and
standard inherited credentials, and atomically replaces the report. Runners still
own their test discovery, isolated interpreters, source identity and native policy.
Use `python -m build_manager.reporting --start TEST_ROOT --output REPORT.xml
--suite SUITE_ID --fail-on-skip` for ordinary stdlib unittest discovery. This helper
is an optional execution/reporting API; it imports no Qt or project code.

Logistics now declares host contracts/UI, Android native/runtime, iOS native and
complete tester acceptance. Its existing isolated runner emits measured JUnit
cases, and reviewed tester workflows require tooling, desktop UI, mobile-host and
full native/runtime acceptance before
preparation and upload. iOS release coverage always includes iPhone, Duo and iPad;
standalone iPad coverage remains optional. Imported iOS runtime evidence remains
an explicit file reference and a retained acceptance artifact.

Blue Hole now declares portable contracts, Blender integration, package inspection
and complete release acceptance. Release native validation installs the exact ZIP
in isolated Blender directories and records its checksum. Full case inventories,
no-skip policy and exact-source hosted evidence gate its reviewed GitHub draft.
Source implementation and portable integration are present in both repositories;
real native/hosted acceptance and committed dependency-pin rollout remain separate.
