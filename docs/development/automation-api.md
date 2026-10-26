# Headless automation API

`build_manager.api` is the manager's in-process automation facade; the
[CLI](../user/cli.md) provides the subprocess interface with `cli_schema=1`.
Both delegate to existing adapters, Plan/Phase contracts, Executor and recovery
mechanisms. No Qt or project modules are imported into the manager process.
Package startup places its fixed checkout-local `Python/` source root first on
the import path so editable console entry points find the pinned commonUtils
from any working directory. A missing submodule fails with setup guidance;
there is no search for sibling checkouts or installed replacements.
The project bridge continues to run in its declared interpreter with structured
JSON stdin/stdout. `API_VERSION` is 1; Plan/result schema versions are separate.

## Python surface

```python
from pathlib import Path
from threading import Event
from build_manager.api import (
    ManagerAPI, plan_info, run_plan, summarize, read_status, read_logs, review_run,
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
result = summarize(report, '/tmp/check-run')
tail = read_logs('/tmp/check-run', 'check', tail_lines=40, max_bytes=16384)
```

The example names are project-defined placeholders. `ManagerAPI.registry` exposes
the existing Registry for registration/selection changes. Facade methods:

| Method | Result and behavior |
| --- | --- |
| `capabilities(project=None)` | Registration, descriptor, host target/operation/backend mapping and journey; descriptor reads only |
| `inputs(project=None)` | Declared fields, adapter defaults and dynamic input choices; invokes trusted project code |
| `prepare_plan(operation, target, backend, *, project=None, **values)` | Plan from the isolated adapter; validates declared choices |
| `prepare_journey(goal, platforms, destinations, *, project=None, **values)` | Validated combined Plan; optional `backends` maps platform to execution host |
| `history(project=None, limit=20)` | Project-owned recent report paths and statuses; limit 1–100 |

Planning values include `revision`, `pattern`, `suite`, `release_tag` and
`run_overrides`, as applicable to the adapter. The facade does not invent suites,
destinations, snapshots or release policy. Inputs remain subject to the adapter's
existing declaration and protected credential rules.

## Execution and evidence

`run_plan(plan_or_path, output, *, confirmed=False, resume=False,
approval_identities=None, expected_identity=None, cancelled=None, event=None)`
returns the complete Executor report. It does not print. `output` becomes an
absolute path. Fresh runs require a new output directory; resume requires matching
retained plan/report identities and the existing engine identity/recovery checks.

`cancelled` is a `threading.Event`; the caller owns signal/event integration.
`event` receives existing executor dictionaries on worker threads and must be
thread safe. Callback failures are caller errors; callbacks should not raise.
Calls block until the executor finishes or reaches review. The CLI installs and
restores SIGINT/SIGTERM handlers around execution and review.

For delivery, call `review_run(output, *, cancelled=None)` to verify prerequisites
and obtain pending external step identities. It returns `identity`, `plan`,
`status`, `approvals` and `prerequisites` with retained/original artifact hashes.
Then pass `approval_identities={step: digest}`, `confirmed=True` and `resume=True`
to `run_plan`. Approval applies only to pending explicit external phases. The API
compares the reviewed digest and the executor checks it again at the effect gate.
No review command executes a phase. Authorization must come from the caller's
operator, not from the mere availability of a digest.

`read_status(output, full=False)` reads an atomic persisted snapshot. Compact
results use `summarize(report, output)`: status, counts, per-phase diagnostics,
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
Original phase results remain unchanged. Unknown external outcomes and pending
artifact approvals retain their existing recovery requirements.
