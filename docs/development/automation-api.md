# Headless automation API

`build_manager.api` is the manager's in-process automation facade; the
[CLI](../user/cli.md) provides the subprocess interface with `cli_schema=1`.
Both delegate to existing adapters, Plan/Phase contracts, Executor and recovery
mechanisms. No Qt or project modules are imported into the manager process.
Standalone package startup binds its checkout-local `Python/` source root so
editable console entry points find the pinned commonUtils from any working
directory. Adapter processes explicitly select `BUILD_MANAGER_DEPENDENCIES=project`
and supply their own source root before importing the manager, preserving the
project's commonUtils in either import order. A missing manager submodule fails
with setup guidance; there is no search for sibling checkouts or replacements.
The project bridge continues to run in its declared interpreter with structured
JSON stdin/stdout. `API_VERSION` is 1; Plan/result schema versions are separate.

## Python surface

```python
from pathlib import Path
from threading import Event
from build_manager.api import (
    ManagerAPI, plan_info, run_plan, summarize_run_report, read_status, read_logs, review_run,
)

api = ManagerAPI(registry=Path('/private/manager-config'))
capabilities = api.capabilities(project='REGISTRATION_ID')
plan = api.prepare_plan('Check', 'native', 'Local',
                        project='REGISTRATION_ID', revision='working-tree')
plan.save('/tmp/check-plan.json')
reviewed = plan_info(plan)  # inspect the returned plan before execution
cancelled = Event()
report = run_plan(plan, '/tmp/check-run', expected_identity=reviewed['identity'],
                  cancelled=cancelled)
result = summarize_run_report(report, '/tmp/check-run')
tail = read_logs('/tmp/check-run', 'check', tail_lines=40, max_bytes=16384)
```

The example names are project-defined placeholders. `ManagerAPI.registry` exposes
the existing Registry for registration/selection changes. Facade methods:

| Method | Result and behavior |
| --- | --- |
| `capabilities(project=None)` | Registration, descriptor, host target/operation/backend mapping and journey; descriptor reads only |
| `inputs(project=None)` | Declared fields, adapter defaults and dynamic input choices; invokes trusted project code |
| `tooling_status(project=None)` | Optional read-only bootstrap readiness before normal adapter imports |
| `update_tooling(project=None, *, confirmed=False)` | Explicit project-owned repair to its declared dependency; blocked active environments remain untouched |
| `prepare_plan(operation, target, backend, *, project=None, **values)` | Plan from the isolated adapter; validates declared choices |
| `prepare_journey(goal, platforms, destinations, *, project=None, **values)` | Validated combined Plan; optional `backends` maps platform to execution host |
| `retire_run(run_name, *, project=None, confirmed=False)` | Retire one retained run and release its holds after confirmation. `retire_workflow` remains available for existing callers. |
| `history(project=None, limit=20)` | Project-owned recent report paths and statuses; limit 1–100 |

Planning values include `revision`, `pattern`, `suite`, `release_tag` and
`run_overrides`, as applicable to the adapter. The facade does not invent suites,
destinations, snapshots or release policy. Inputs remain subject to the adapter's
existing declaration and protected credential rules.

## Execution and evidence

`run_plan(plan_or_path, output, *, confirmed=False, resume=False,
approval_identities=None, expected_identity=None, cancelled=None, event=None,
reconcile=None, event_format='snapshot')`
returns the complete Executor report. It does not print. `output` becomes an
absolute path. Fresh runs require a new output directory; resume requires matching
retained plan/report identities and the existing engine identity/recovery checks.

`cancelled` is a `threading.Event`; the caller owns signal/event integration.
`event` receives dictionaries on executor threads and must be thread safe.
The default `event_format='snapshot'` preserves existing phase events.
Choose `event_format='compact'` to transport running test inventories as
versioned frames. Lifecycle events, terminal phase records and retained reports
keep their existing shape. Callback failures are caller errors.
Calls block until the executor finishes or reaches review. The CLI installs and
restores SIGINT/SIGTERM handlers around execution and review.

For compact events, feed each dictionary to
`build_manager.event_stream.ExpandEvents().apply(event)` using one decoder per
ordered stream. Pass its returned events to the existing observer and ignore
`None`. For CLI JSONL, pass the inner `event` dictionary. The bundled UI uses
the same decoder and reads the retained report at completion.

A `type="test_inventory"` frame with `progress_schema=1` identifies the phase
in `id` and its inventory generation in `stream`. `sequence` increases within
that generation. The first frame of a checkpoint sets `checkpoint=true` and
clears the generation's provisional inventory. Data frames carry up to 64
`[index, row]` entries for the named `field`, either `test_files` or
`live_tests`. A commit frame carries the inventory `sizes`, the phase metadata
in `phase`, and the inventory `fields` to attach to that event. Apply the batch
only at commit. Sizes truncate inventories when a runner rewrites a report.

Observers that attach late or miss a sequence wait for a checkpoint before
publishing another inventory update for that phase. Running phases send an
initial checkpoint and refresh it about once a minute after reporting starts,
including while a test is quiet. Terminal phase events remain usable even if
an observer missed the entire live stream. For a disconnected stdout reader,
the transport must still drain stdout and deliver subsequent complete lines
from the same execution. Use `status --full` or the retained `result.json`
to recover authoritative evidence after an interruption.

On resume, optional `reconcile(step_id, row)` supplies project-owned, read-only
outcome verification for an uncertain external phase. The executor invokes it
under the run's supervisor lock. Return an evidenced receipt with `status='passed'`
for an already completed effect, or `status='not-performed'` to mark it interrupted
and eligible for the existing retry/review rules. Other receipt statuses fail
closed. Without this callback, unknown effects remain unknown and are not replayed.

New phase attempts retain an operation-ID-bound `*.launch.json` record.
`launching` is persisted before the process constructor; `started` follows its
successful return. A completed admission failure or POSIX creation/exec failure
with explicit `not_started` proof remains failed and has `retryable=True`.
Failures after launch, uncertain constructor errors and interrupted running intents
remain unknown for external effects. Windows constructor errors remain conservative
because an error may occur after its child starts. No duration, missing-log check,
or older unknown record is treated as proof that an effect did not happen.

For delivery, call `review_run(output, *, cancelled=None)` to verify prerequisites
and obtain pending external step identities. It returns `identity`, `plan`,
`status`, `approvals` and `prerequisites` with retained/original artifact hashes.
Then pass `approval_identities={step: digest}`, `confirmed=True` and `resume=True`
to `run_plan`. Approval applies only to pending explicit external phases. The API
compares the reviewed digest and the executor checks it again at the effect gate.
No review command executes a phase. Authorization must come from the caller's
operator, not from the mere availability of a digest.

`read_status(output, full=False)` reads an atomic persisted snapshot. Compact
results use `summarize_run_report(report, run_directory)` (also available as `summarize(report, output)`): status, counts, per-phase diagnostics,
failed test samples and report location. `full=True` returns `result.json` data.
`read_logs(output, step, tail_lines=40, max_bytes=16384)` validates the retained
plan/report pair and a declared step log; it rejects traversal and symlink logs,
reads at most 64 KiB and returns a bounded tail with `truncated` and `bytes_read`.
This is inspection of trusted local evidence, not a sandbox for hostile files.

Preflight and evidence errors raise the existing `OSError`, `ValueError`,
`RuntimeError` or `KeyError`; cancellation during verification may raise
`commonUtils.runtime.operations.OperationCancelled`. Execution failures normally
return a report whose status is failed/cancelled/unknown/awaiting_review. Consumers
must inspect status. Python callers own output serialization; the CLI adds
credential redaction and versioned JSON envelopes. It retains existing
registration/planning field names. CLI syntax errors return structured JSON.

The legacy `python -m build_manager PLAN --output RESULTS` event interface remains
available for existing GUI/process consumers, including its cancellation marker
and reviewed-step arguments. New automation should use `build-manager` or
`python -m build_manager.cli` for compact results and discovery.

## Validation

From the repository root, using the locked manager environment and pinned real
commonUtils source root:

```sh
PYTHONPATH=Python .venv/bin/python -m unittest discover -s Python/tests -p test_cli.py -v
PYTHONPATH=Python .venv/bin/python -m unittest discover -s Python/tests -p test_registry.py -v
PYTHONPATH=Python .venv/bin/python -m unittest discover -s Python/tests -p test_workflows.py -v
```

The CLI contracts use disposable isolated project interpreters, real harmless
child processes and synthetic delivery effects that only write fixture files.
They cover argument preservation, descriptor-only discovery, preparation/run,
compact failures, bounded log reads, review/resume identity checks, changed
artifacts, uncertain outcomes, credential redaction, headless imports, existing
module execution and POSIX signal cancellation. They do not establish native
Windows process cancellation, VM/device operation or actual provider deployment
acceptance. No production build, publish or dispatch is needed to validate these
contracts. Keep raw evidence under ignored `test-results/`.

## Shared presets and reviewed engine continuation

`ManagerAPI.presets(project)`, `save_preset(name, choices, project=..., replace=False)`
and `prepare_preset(name, project=...)` use the existing registry selection schema.
Preset preparation routes through the ordinary bridge operation/journey validators;
project code remains isolated. GUI registry values are reused, with no second
preset store. `start` is prepare plus ordinary supervised execution.

`review_run` returns an optional `engine_change` binding the retained/current
runtime identities. `run_plan(..., resume=True, engine_review=identity)` accepts
only that exact reviewed pair. The executor records a transition and retained
phase IDs in `engine_history` after locked recovery verifies prior artifacts.
Retained phase records remain unchanged. Recovery invalidates successful
nonexternal consumers and cleanup transitively over `dependencies` and
`waits_for` when a prerequisite will run again. An unscoped whole-workflow cleanup
refreshes whenever work is scheduled. This prevents a prior no-op cleanup from
admitting concurrent owners on resume. Completed/unknown external effects remain
retained; stale external cleanup blocks automatic continuation instead of being
replayed. Unknown outcomes and pending artifact approvals retain their existing
recovery requirements.

`run_plan(..., resume=True, confirmed=True, approve_steps=('ready-step',),
retry_failed=False)` verifies and binds only the named pending external actions.
It avoids a caller-maintained approval JSON document. Duplicate, nonpending,
unknown or overlapping named/identity scopes are rejected before execution;
retained prerequisite bytes and engine changes keep their existing guards.
Explicit `approval_identities` remains supported for clients retaining review
digests. The compact report's additive `continuation` object exposes completed,
pending, failed and unknown actions plus suggested command argument arrays.
These are guidance, not authorization. A successful independent delivery leaves
other failed required branches and the overall failed status unchanged.

`ManagerAPI.prepare_retained_delivery(run_directory, destinations, project=...,
run_overrides=...)` returns a fresh plan through an optional declared adapter
action. It neither starts that plan nor reinterprets an uncertain install as
authorization. See [the retained-input contract](adapters.md#optional-delivery-from-retained-inputs)
for the exact payload, ownership and validation boundaries. The manager does not
require current HEAD to equal the retained source; the project must verify its
retained snapshot and selected platform's prerequisite closure.
