# Connect a project's tests to the manager

Follow this walkthrough to register a project and see a real test file and its
case outcomes. Start with the manager's [locked setup](../user/setup.md), including
its pinned commonUtils submodule. Commands below run from the manager repository
root on macOS/Linux. On Windows use the corresponding `.venv/Scripts/python.exe`
paths and PowerShell environment syntax. All CLI examples use
`python -m build_manager.cli`, so only the interpreter path changes on Windows.
No provider account or native SDK is needed. This example adds no delivery destination.

## Understand the three lists

The manager does not scan a registered project and automatically turn every test
into a selectable workflow. A project supplies three related views:

| View | Supplied by | What it establishes |
| --- | --- | --- |
| Available suite choices | `build-project.json` → `test_suites` | Labels and platform/operation applicability; adapter must implement selection |
| Planned checks and optional files | Adapter-generated `Phase` objects and `test_files` | Commands, gates and declared file previews for the captured source |
| Observed cases and timings | Declared JUnit artifacts | Actual results; optional live events provide provisional progress |

`build-tests.json` declares execution roots and prerequisites for an adapter
using the manifest API. It does not populate the suite selector or produce case
results by itself. A new test within an existing root normally needs no new suite.

## 1. Prepare the small example project

The example project lives in `Python/tests/fixtures/testing_project/`.
Its placement keeps it available when local test runs capture uncommitted
manager sources.
Read its files before adding it: registration authorizes the bridge to execute project code. It contains:

| File | Responsibility |
| --- | --- |
| `labels.py` | Example behavior: trim a name and give blank input a visible default |
| `tests/test_labels.py` | Two standard-library unittest cases using synthetic strings |
| `build-project.json` | Project identity, interpreter, bridge, capabilities and selectable suite |
| `build-tests.json` | Execution suite `labels`, its test root and validation group |
| `bridge.py` | Schema-1 requests/responses, source copy, plan creation, file inventory and JUnit declaration |

Create a separate project interpreter using the manager
environment's supported Python, then explicitly install this reviewed manager
into it. The pip step may need network access for uncached build requirements. The project retains its environment; registering it does not install
anything. From the manager root:

```sh
.venv/bin/python -m venv Python/tests/fixtures/testing_project/.venv
Python/tests/fixtures/testing_project/.venv/bin/python -m pip install --no-deps -e ./Python
```

Run the tests without the manager first, from the example directory:

```sh
cd Python/tests/fixtures/testing_project
.venv/bin/python -m unittest discover -s tests -v
cd ../../../..
```

Expect two passing cases. The final `cd` returns to the manager root. The
bridge's planned commands use their captured source as the working directory,
so they need no shell activation or custom import-path setting.

## 2. Register, prepare and inspect

Use a dedicated example registry to avoid changing your normal selected project:

```sh
.venv/bin/python -m build_manager.cli --registry test-results/onboarding-registry add Python/tests/fixtures/testing_project
.venv/bin/python -m build_manager.cli --registry test-results/onboarding-registry capabilities --project org.example.manager-testing-walkthrough
.venv/bin/python -m build_manager.cli --registry test-results/onboarding-registry plan \
  --project org.example.manager-testing-walkthrough \
  --operation Test --target host --backend Local --suite labels \
  --output test-results/onboarding-plan.json
.venv/bin/python -m build_manager.cli show-plan test-results/onboarding-plan.json
```

The capabilities contain the named unit-test suite. The plan contains one test
phase, `labels`, a `test_labels.py` file preview, a command using the project's
interpreter, and an XML artifact explicitly typed `junit`. The bridge copies only
its declared public source into a fresh project-owned `test-results` workspace
and records the copied bytes' hashes. Inspect that source and the command before
execution. Omitted suite means the complete project; this example has one suite.
Unknown suites, focused patterns and non-working-tree revisions are rejected.

## 3. Run and inspect real results

```sh
.venv/bin/python -m build_manager.cli run test-results/onboarding-plan.json --output test-results/onboarding-run
.venv/bin/python -m build_manager.cli status test-results/onboarding-run
```

Use a fresh run-output directory for every attempt. The run should pass and retain
two measured cases, their final XML report and the phase log. The optional reporting
helper emits structured case progress when executed by the manager. A declared file
preview does not imply its tests ran; the retained report supplies actual outcomes.

To see the same path in the GUI, add `Python/tests/fixtures/testing_project` through the normal
project picker, choose advanced Test / host / Local and the display-name suite,
then inspect and run a fresh plan. CLI's example registry is separate from the
GUI's normal registry. The descriptor supplies selection, `test_files` supplies
planned files, and final JUnit supplies result cases.

As a learning exercise, temporarily replace the blank-name assertion's expected
`Untitled` with `Wrong`. Prepare a fresh plan and use a different run-output
folder. Expect a failed phase with that assertion in case details and retained
JUnit even though the runner exits nonzero. Restore the test and prepare again.
Existing plans keep their own source copies. Also try an unknown `--suite`: it
must fail planning rather than silently run broader coverage.

When finished, use the `registration` UUID returned by `add` (or shown by
`list`) to remove the CLI example registration from its dedicated registry.
`remove` requires that UUID:

```sh
.venv/bin/python -m build_manager.cli --registry test-results/onboarding-registry remove REGISTRATION_ID
```

If you also added the project in the GUI, remove that registration separately.
Registration removal does not delete source or output. After preserving needed
evidence, delete only the example's `.venv/` and `test-results/`, plus the manager's
`test-results/onboarding-registry/`, `onboarding-plan.json` and `onboarding-run/`
and any additional run folders you explicitly created for this exercise. In a real
project, use its retention policy and retain useful failure evidence first. Do not
remove this manager's own environment, other registrations or unrelated results.

## 4. Apply the pattern to your project

| Capability to add | Prepare or change | Verify before extending further |
| --- | --- | --- |
| Basic registration | Project-owned `build-project.json`, bridge and installed project interpreter | `add`, `capabilities`, supported/unsupported requests |
| Run existing tests | Runner plus `build-tests.json`, or custom adapter-created phases | Exact cwd, interpreter, root and nonempty discovery |
| Select a named suite | Descriptor `test_suites` and explicit bridge/adapter routing | Exact selection and intersection of supported focused patterns; reject inapplicable IDs |
| Dependency suites | Manifest `owner`, `after`, interpreter map and initialized pinned submodule | Required dependency precedes consumer; failed dependency blocks it |
| Planned file preview | `Phase.test_files` from the same captured source | Files belong to the selected suite; preview does not claim execution |
| Cases and measured timings | Runner's unique JUnit output plus phase `artifacts` and `artifact_types` | Passing and failing attempts; missing/invalid/empty evidence fails |
| Live test/file progress | Optional `emit_test_progress` or reporting helper | Provisional progress reconciles with authoritative final JUnit |
| Classification preflight | Project checker and manifest `test_structure` | Invalid/missing source labels block tests without importing them |
| Smoke gates | Runner with scope support, classifications and suite `smoke_args` | Failed smoke blocks broad phases; full evidence remains distinct |
| Native/acceptance checks | Project-owned drivers, exact required case/platform/skip policy and cleanup | Real target identity and packaged behavior; no passing substitution for unavailable coverage |
| Build or delivery | Project builders, source/package identities, resources and destination-dependent gates | Exact prepared artifacts, cleanup and declared effects; follow the journey contract |

The example deliberately implements one test root and no release policy. When
adding suites, derive file inventories from each suite's selected root, give each
phase a distinct report path and preserve all prerequisite edges. Add handling
for settings only when your project has settings. Keep protected credentials as
references, not source, descriptors, test fixtures or reports.

`test_manifest.phases()` supports one runner argument template and a named
interpreter map. If different suites use different frameworks, consume
`discover()` and construct their phases with each framework's command. Each
framework can produce JUnit; unittest and the optional reporting helper are not
requirements for registration. Dependency `owner` currently represents a pinned
Git submodule, not an arbitrary installed package or sibling checkout.

For smoke scopes, the example's stdlib reporting command does not accept
`--profile` or `--mode`. Use a runner that implements those arguments before
adding `smoke_args`. Classification is opt-in; `test-structure.json` is Logistics'
project format, not a mandatory manager file. The manager invokes your declared
checker without importing its enum or tests.

Use [test manifests](test-manifests.md) for discovery and smoke dependencies,
[test organization](test-organization.md) for JUnit, file inventories and progress,
[adapters](adapters.md) for the subprocess protocol, and
[journey contracts](journey-contract.md) for combined validation and delivery.
Production adapters additionally own reproducible source capture, dependency and
toolchain identities, input validation, retention and release eligibility. Do not
copy Logistics-specific gates or signing rules into another project's template.

## Keep the example working

From the manager root, run:

```sh
.venv/bin/python -m unittest discover -s Python/tests -p test_example_project.py -v
```

These contracts use disposable copies and the selected test interpreter. They
verify descriptor metadata, planned files, source-copy isolation, real passing and
failing JUnit, rejected selections, and CLI registration/planning/execution with
a disposable isolated interpreter and registry. The CLI contract binds this
reviewed manager source through a private `.pth` file without network or package
installation. It does not exercise the GUI or pip packaging. When changing setup or CLI instructions, also repeat the
registration, planning and execution steps above with a disposable project
interpreter and a separate registry.

## Troubleshoot one layer at a time

| Symptom | Check |
| --- | --- |
| Project cannot be added | Descriptor schema, host interpreter mapping and checkout-relative bridge path |
| Suite missing from selection | Descriptor metadata and exact platform/operation capability names |
| Manifest suite never enters a plan | Adapter calls the manifest API for the intended group and preserves its results |
| Wrong tests run | Adapter suite routing, framework pattern semantics and captured-source root |
| Planned file appears but results do not | Framework discovery, selected scope and declared nonempty JUnit artifact |
| No live progress | Runner producer opt-in; final JUnit can still provide complete results |
| Required native suite skipped | Fail the owning acceptance gate; report the missing host/runtime prerequisite |
| Source edit does not affect an old plan | Prepare a fresh source capture and plan; inspect its identity |

[Developer index](development.md) · [Documentation home](../docs.md)
