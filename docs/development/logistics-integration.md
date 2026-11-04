# Trace a Logistics workflow

Use this guide when joining manager development or investigating a Logistics
run. Start in the manager checkout with its locked interpreter. Logistics must
already be registered for the discovery commands below. Use the unique local
registration name shown by `list`; examples assume it is `Logistics`.

## Identify the checkout before loading its tools

```sh
.venv/bin/python -m build_manager.cli list
.venv/bin/python -m build_manager.cli inspect Logistics
.venv/bin/python -m build_manager.cli capabilities --project Logistics
.venv/bin/python -m build_manager.cli presets --project Logistics
.venv/bin/python -m build_manager.cli history --project Logistics --limit 5
```

These commands inspect registration, descriptor, saved choices and retained
evidence without calling a project adapter. Registration access uses the existing
configuration migration mechanics; these are not an offline configuration backup
tool. A project ID can match several worktrees: choose a unique registration name
or exact checkout path. Inspect the resolved root before investigating its files.
Use a registration UUID with older CLI versions whose `inspect` only accepts keys.

Do not use `inputs` as a static inventory: it queries the trusted adapter.
`check-project` also loads settings; `check-project --prepare` prepares its matrix
and may capture source or prune owned outputs. Planning is not a read-only probe.
See [CLI scope](../user/cli.md).

## Follow the owning code

Paths in the Logistics column are relative to the chosen Logistics checkout;
paths in the manager column are relative to `Python/build_manager/` here.

| Question | Logistics owner | Manager owner |
| --- | --- | --- |
| Which operations, suites, hosts and inputs are advertised? | `build-project.json` | `registry.py`, `adapter_sdk.py`, `journeys.py`, `run_fields.py` |
| What crosses the interpreter boundary? | `logistics_build/manager_bridge.py` | `bridge.py` |
| How do choices become commands? | `logistics_build/build_project.py`, `manager_journeys.py` | `preparation.py`, `models.py` |
| Which source/settings are captured? | `logistics_build/build_snapshots.py`, `mobile_build/deployment/manager_settings.py` | Bridge context and plan validation; no Logistics snapshot policy |
| Which tests and release gates are required? | `logistics_build/manager_suites.py`, `validation_plans.py`, evidence helpers | `test_manifest.py`, `test_results.py`, scheduling and artifact mechanisms |
| Who supervises processes and recovery? | Backend/tool arguments and project recovery applicability | `executor.py`, `run_session.py`, transports, `workflows.py` |
| Who decides package, signing and recipient policy? | `manager_packages.py`, `manager_devices.py`, `mobile_build/deployment/` | Review, approval identities and generic delivery mechanisms |
| Who owns stored outputs? | `logistics_build/build_retention.py` | `retention.py`, storage presentation and holds |

Trace a single request: CLI/GUI selection → manager preparation → isolated JSON
bridge request → Logistics plan → manager `Plan` validation → reviewed execution
→ retained report. GUI and CLI admission can differ; inspect the actual plan and
its declared effects before starting it. A saved preset contains choices, not
approval. Device-only delivery may omit optional validation when Logistics permits
it; that does not prove release gates passed.

## Distinguish the three dependency identities

Read Logistics' `build-manager-dependency.json` for its declared dependency.
Inspect `build_manager.__file__` in the selected project interpreter for the
installed source location. Read a retained report's `engine` record for the
manager/commonUtils identities captured during that run. These can differ in an
editable development setup. The source choice exposed by a workflow is a further
project-owned decision; do not infer it from the installation alone.

The manager requires its own real `Python/commonUtils` submodule. Fresh standalone
manager processes bind that source root. Adapter subprocesses receive
`BUILD_MANAGER_DEPENDENCIES=project`: importing the manager then preserves the
project interpreter's dependency resolution in either import order. The bridge
clears inherited `PYTHONPATH`/`PYTHONHOME`; the project's bridge supplies its own
source roots or installed dependencies. Direct project tooling must set this
context before importing either package. Do not set it in a global shell profile.

For a direct compatibility probe, supply explicit paths and the project's Python:

```sh
BUILD_MANAGER_DEPENDENCIES=project PYTHONPATH="/explicit/project/Python:/explicit/manager/Python" \
  /explicit/project/.venv/bin/python -c 'import build_manager, commonUtils; print(commonUtils.__file__)'
```

Legacy callers that preload commonUtils remain supported, but new integrations
must use the explicit context so correctness does not depend on import order.
Runtime `engine.commonUtils` now identifies the dependency actually loaded. The
manager's own pin remains the source used by its standalone process and by exact
dependency packaging; the context never changes a pin or discovers a sibling
checkout. Start a separate manager process with its interpreter and manager
context when leaving a project process; changing an environment variable cannot
replace a library already imported in that process.

## Diagnose an outcome before choosing recovery

For an exact retained run directory, use:

```sh
.venv/bin/python -m build_manager.cli status /absolute/path/to/run
.venv/bin/python -m build_manager.cli logs /absolute/path/to/run --step exact-step-id
```

`status` exposes failing JUnit cases in `failed_tests`; a log tail can contain only
the last successful tests. Inspect the structured failures before assuming a
validation failure is infrastructure. Missing prerequisites, failed assertions,
cancelled work, pending review and unknown external outcomes require different
actions. Unknown installation/upload outcomes need reconciliation before replay;
a locked-device error alone does not authorize another installation.
See [workflow recovery](../user/workflows.md).

For a manager fix, run its owning contract tests first. Then validate the affected
Logistics adapter behavior with that checkout's interpreter and dependency source,
using isolated fixtures that do not prepare live work or touch devices. The
[consumer acceptance contract](adapters.md#explicit-cross-consumer-acceptance)
records explicit source/interpreter selections. Native acceptance remains a
separate step on explicitly authorized hosts.

[Developer guide](development.md) · [Architecture](architecture.md)
