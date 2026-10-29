# Discovering project and dependency tests

For registration through actual case results, use
[the runnable project walkthrough](adding-project-tests.md). This reference covers
execution discovery; descriptor suite choices and JUnit results are separate.

Projects declare their test inventory in `build-tests.json` at the checkout root.
The headless `build_manager.test_manifest.discover(root, group)` API returns the
selected suites and their transitive prerequisites in dependency order. It reads
data and Git metadata; it does not import tests, search neighboring repositories,
install dependencies or execute suites. The project adapter calls it against the
same captured source used by its build plan.

## Minimal convention

A project with a single conventional test root can start with:

```json
{"schema": 1, "suites": [{"id": "project", "groups": ["validation"]}]}
```

Exactly one of `Python/tests` or `tests` must exist; otherwise declare `directory`.
New Python test files should use `test_*.py` with meaningful test case names.
Organize larger suites under unit, contracts, integration, ui, native and
acceptance directories as described in [test organization](test-organization.md).
Keep suite IDs stable even if directories move. A manifest declares suite roots;
the project runner owns file discovery, framework support and case inventories.
No new directory layout is imposed on established shared libraries.

## Dependencies and prerequisites

```json
{
  "schema": 1,
  "suites": [
    {"id": "shared", "owner": "Python/commonUtils", "directory": "tests",
     "interpreter": "desktop"},
    {"id": "project", "groups": ["validation"], "after": ["shared"]}
  ]
}
```

`owner` defaults to the selected project root. A different owner must be a tracked
Git submodule inside that checkout, initialized at the indexed gitlink commit.
Test paths must remain within their owning checkout, including after resolving
symlinks. Missing suites, unknown prerequisites, duplicate IDs, cycles, mismatched
pins and ambiguous conventional roots fail planning with an explanation. Shared
libraries need no new files or pin changes: the consuming project explicitly
chooses which dependency suites its policy requires. This does not recursively
opt every dependency into testing or guess tests from arbitrary directories.

`groups` selects suites for an adapter-owned operation; `after` pulls in required
prerequisites even when they have no group. Multiple consumers can run in parallel
after a shared prerequisite passes. A failure blocks success-dependent consumers.
`timeout` is positive seconds, default 900. `interpreter` is an adapter environment
name, default `project`; discovery never guesses a virtual environment.

## Connecting an adapter

Use `phases(root, group, interpreters, runner, environment=...)` to create generic
test phases with explicit success dependencies. `interpreters` maps manifest
names to the project's configured isolated executables. `runner` is an argument
tuple; a whole argument `{directory}` is replaced with the resolved test root.
No shell command is evaluated. For example an existing isolated project runner:

```python
from build_manager.test_manifest import phases
checks = phases(snapshot, 'validation', {'project': project_python,
    'desktop': desktop_python},
    ('Python/tests/run_regressions.py', '{directory}', '--isolate-modules'),
    environment=environment)
```

Adapters with another framework can consume `discover` directly and preserve each
row's `after` dependencies while constructing their commands. Attach JUnit evidence
using the project's runner and [reporting helpers](test-organization.md), so the
manager can show actual counts, timings and failures. Merely declaring a suite
must never count as running it. Native acceptance, source identity, required
release scope and delivery policy remain owned by the project.

Logistics uses this manifest for desktop and mobile host validation. Pinned
commonUtils tests precede Logistics tests; mobile project host suites then precede
native/runtime acceptance. Focused advanced tests intentionally run only their
selected scope and cannot replace full delivery gates. The exact phases and
prerequisites are visible in Review and Run; the configuration proposal is a
summary until the adapter has prepared its plan.

- [Test organization](test-organization.md)
- [Adapter contract](adapters.md)
- [Documentation home](../docs.md)


## Test structure and smoke gates

Projects can opt into source classification validation by declaring
`test_structure` at the root of `build-tests.json`:

```json
"test_structure": {
  "command": ["-m", "project.test_structure", "--check"],
  "interpreter": "host"
}
```

The interpreter is an adapter-owned environment key. The checker must inspect
source before importing tests and exit nonzero with file/line diagnostics for
missing, invalid or contradictory classifications. The manager emits a
`test-structure` setup phase and makes every selected test phase depend on it.
A failed checker blocks tests; always-run cleanup remains runnable. The captured
checkout must contain the checker and its declared test roots.

A suite may additionally declare `smoke_args`, for example
`["--profile", "smoke", "--mode", "fast"]`, understood by its owning runner.
The manager creates `<suite>.smoke` phases, preserves prerequisite ordering within
the smoke group, then gates all broad suites on all selected smoke phases. This
lets application smoke checks run before a complete dependency regression suite.
Smoke checks may be repeated in a complete diagnostic run; a smoke receipt never
substitutes for complete release coverage.

The standard source contract used by Logistics and commonUtils is the enum
`TestStage.SMOKE`, `TestStage.REGRESSION`, `TestStage.EXTENDED`. Python modules
provide `TEST_STAGE`, with optional `@stage(...)` class/method overrides. Native
standalone drivers and Go/Swift/Java sources can express the same enum member in a
`TEST_STAGE = TestStage.MEMBER` source comment. A project's validator owns its
inventory and language adapters; the manager must not import project test code
or assume which tests deserve each stage.

Profiles are cumulative: smoke, daily (smoke + regression), full (all stages).
Runners must distinguish selected, excluded and not-run coverage. Fast mode may
stop after a failed smoke gate, explicit fail-fast may stop at the first failure,
and diagnostic runs continue independent cases. Stateful native journeys may
stop when their retained state becomes invalid. Cleanup always runs. JUnit may
encode not-run entries as skipped with an explicit reason, while the owning JSON
report retains not-run status and incomplete coverage. Unrun or narrowed evidence
cannot satisfy a full release gate. Missing required dependencies and malformed
classification are preflight failures, not passing skips.
