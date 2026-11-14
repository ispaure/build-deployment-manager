# Project integration and guest workloads

Use a command project for local test/build commands; use an API-1 adapter for
custom source capture, selectable suites, settings, native builders or release
policy. Both feed the existing Plan/Phase executor and retain normal review,
logs, artifacts and failure behavior. Neither path discovers or executes tests
merely because their files exist.

## Command projects

A project can contain just `build-project.json`, without a Python bridge or
project Python environment. Executables still need their own installed dependencies.
The command descriptor uses schema 1 / adapter API 1 with `name`, `project_id`
and this catalog:

```json
{
  "schema": 1,
  "adapter_api": 1,
  "project_id": "org.example.widget",
  "name": "Widget",
  "commands": {
    "source": ["package.json", "package-lock.json", "src"],
    "operations": {
      "Build": [{
        "id": "build",
        "argv": ["npm", "run", "build", "--", "--outDir", "{output}"],
        "effect": "build",
        "timeout": 600
      }]
    }
  }
}
```

This example assumes the project's build script accepts `--outDir`; it does not
install npm packages. Declare dependency preparation as an earlier command when
needed. Dependencies must remain isolated to the captured project workspace.

The catalog derives `host` / `Local` capabilities and operation names. Do not
maintain a second capability list. Commands are argument arrays, never shell
strings. Each step has an ID and explicit `test`, `build` or `inspect` effect.
Optional fields are `cwd` (relative to captured source), `dependencies`,
`environment`, `timeout`, `artifacts` and `artifact_types`. Artifact paths are
relative to the generated artifacts directory; `junit` reports provide test cases.
Commands must create their declared outputs. Dependencies name preceding steps.

`{source}`, `{output}` and `{project}` are literal substitutions inside arguments
and environment values. `{project}` allows an explicit project interpreter path,
for example `{project}/.venv/bin/python`; commands should read application inputs
from `{source}`. This is trusted executable configuration, not a sandbox.

Only declared ordinary source files/directories are copied. Links, traversal,
`.git`, `.venv`, `__pycache__` and `test-results` inside those inputs are rejected.
Do not select the entire repository with `.`. Captured bytes are hashed and later
working-tree edits do not change the copy. Command changes enter source identity.
Preparation stores fresh copies under the project's results directory. Retention
of those outputs remains the project owner's responsibility; no automatic prune
policy is introduced. Use custom adapters for production snapshot/release policy.
Historical revisions, focused patterns, suite selections, delivery and journeys
are intentionally rejected rather than silently ignored.

## Small adapter facade

`build_manager.adapter_sdk` exposes API_VERSION, Plan, Phase, load_profile,
save_profile, operations_for, backend_options and serve. It imports neither Qt
nor consumers. Existing module imports remain supported; the facade is an additive
entry point, not a replacement for specialized transport APIs.

`serve(handlers)` dispatches schema-1 stdin JSON to an explicitly supplied mapping.
A handler takes `(values, context)` and returns JSON data or a Plan. Context carries
`settings_profile`, `manager_checkout` and account references. Diagnostics printed
by handlers go to stderr; stdout contains one protocol response. Unsupported
actions fail. The project decides which actions exist and owns their behavior.

Use operations_for/backend_options against the same descriptor the manager reads.
Host-specific and operation-specific backend mappings are resolved identically
on both sides. Projects retain their interpreter, manager version and commonUtils
pin; importing the facade never installs or upgrades anything.

### Project settings

The `settings` action returns rows keyed by field ID. Each row declares its
effective `value` and can include `origin`, `label`, `description`, `kind`,
`section`, `read_only` and `visible_when`. Supply the effective source even
for read-only rows when it helps explain an identity, derived value or shared
account. The UI uses declared run-field IDs and known setting namespaces to
place rows under user-facing categories. It uses the adapter's section for
other fields. Existing field IDs continue to be the persistence keys.

`save_settings` receives a partial `changes` object. Merge it into the current
checkout settings and validate the resulting configuration. Omitted fields
retain their stored values. Keep credentials as protected references.

An adapter that supports removing checkout profile overrides can opt in per
field by adding a `reset` object to its row. It declares `overridden` (whether a
checkout override is stored, even if masked), `value` (the effective value
without that override, with the same type as the effective row value), and
`origin` (its source). Use the same effective-settings resolver to compute the
fallback so an environment value can remain in effect. The manager sends an
optional `resets` list of field IDs to `save_settings` only when requested. A
field appears in at most one of `changes` and `resets`. Validate both against
the current schema, remove only the specified checkout keys, and commit
the merged result together. Repeated removal of an absent key is safe. Keep
tracked, guarded, credential and signing settings outside this contract.
Adapters without reset metadata keep the existing request shape.

## Shared guest execution

`build_manager.guest_workload` provides:

- `prepare_windows(client, vm, output, tools, **runtime)`: supplied pinned tools,
  a fresh ownership token, and a durable preparation receipt. Failure preserves
  the exact token for reconciliation. Existing receipt paths are never overwritten.
- `LinuxSession(client, vm, uid, gid)`: an explicit ready Linux guest account and
  a fresh owned workspace using the existing Parallels admission mechanisms.
- `WindowsSession(client, prepared)`: a prepared Windows tools receipt and unique
  source, reports and virtual environment paths for each operation.
- `run_workload(...)`: source staging, isolated environment preparation, project
  dependency setup, plan submission, result collection and conditional cleanup.
- `execute_plan(...)` and `GuestResultLifecycle`: the same submission/evidence
  mechanisms for existing adapters with specialized container or platform setup.

VM creation, OS bootstrap, selection and ownership still live in vm/vm_bootstrap
and the Test machines UI. A session does not silently choose, start, adopt or
replace a VM. The caller explicitly selects a ready guest and verifies its required
OS/architecture. Windows tool preparation explicitly starts its selected guest. The preparation
receipt is locked to prevent concurrent attempts from replacing its ownership record.
Source membership, toolchain pins, dependency recipes, native checks, release
gates, power policy and output retention remain project-owned.

For run_workload, supply `session`, `snapshot`, explicit `members`, a fresh local
`directory`, captured `source`, `backend`, `environment`, cancellation Event,
`prepare(session, execute)` and `make_plan(session)`. Linux additionally supplies
`toolchain={"python": "...", "uv_version": "..."}`. Windows takes its base
interpreter from the prepared receipt and creates a fresh venv per operation.
The project setup callback installs its dependencies and the selected manager into
that interpreter using `execute(argv, environment, timeout)`. The plan callback
uses session.source, session.python and session.reports for remote paths.

An uncertain transfer is inspected by the existing transport. Workload commands
are never blindly replayed. A nonzero setup exit stops before test submission.
Source/backend and plan identity must match the collected report; a passing report
must include every required phase. Collection precedes cleanup. Failed collection
preserves remote evidence; cleanup failure makes the overall result fail.
Cancellation before staging touches no guest. Bootstrap or execution failure still
attempts evidence recovery for the owned workspace.
Unexpected setup-callback exceptions also produce a failed result. Windows results
identify the operation removed by cleanup and explicitly retain the separately
prepared public tools workspace; they do not claim that base workspace was deleted.

Existing Logistics backends use shared plan submission, result collection/cleanup
and Windows tool preparation, retaining their container setup, source recipe,
manager-pin installation and application test policy. New integrations can use the
complete session runner without copying Logistics' backend modules.

### Preserve history when changing a result directory

`results` is the checkout-relative destination for new runs. Declare prior
run directories in the optional `legacy_results` list to include their existing
records in History and storage review. The Manager leaves saved plans, artifacts
and hold owner paths at their original locations. Use an absolute path from
History with `storage --retire-workflow` when multiple roots contain the same run
name. A unique run name still works.

Changing the descriptor changes its digest. Exact-path review and continuation
can still use the original plan and artifacts. Automatic adapter storage
maintenance requires the original descriptor identity and reports a separate
failure if the current descriptor differs. Refreshing registration preserves
that check.

## Validation and compatibility

Run `test_command_project.py`, `test_adapter_sdk.py`, `test_guest_workload.py`, the
registration/onboarding contracts, then the complete isolated manager contracts.
Consumer compatibility must use the consumer's own interpreter/commonUtils and
explicitly identify a candidate manager if testing uncommitted manager changes.
Do not update a dependency pin to an uncommitted or unavailable revision.

Portable guest tests inject staging, setup, execution, retrieval and cleanup
failures. They do not certify native VM bootstrap, OS tools or platform acceptance.
Native checks require explicitly authorized dedicated guests; held VMs and personal
devices remain excluded. Keep raw logs under ignored test-results.

[Developer guide](development.md)


Optional custom actions can be listed in `adapter_actions`. The GUI enables
verification/storage controls only when declared (legacy verification remains
available when the field is absent). Declare both storage_inventory and
delete_storage for a complete cleanup workflow. Command projects expose neither
native verification nor storage deletion. The explicit check-project command is
their readiness diagnostic. `check-project --prepare` also checks applicable named
suite requests without executing the returned plans.
