# CLI for automation and AI agents

Use `build-manager` from the manager environment after [setup](setup.md).
`python -m build_manager.cli` exposes the same interface. Pass arguments as an
argument list when launching it from code. Each project keeps its own interpreter,
operation names, suites, release rules and destinations.

If you have not activated the environment, substitute `.venv/bin/build-manager`
for `build-manager` on macOS/Linux, or `.venv\Scripts\build-manager.exe` on Windows.
Start with `build-manager --help`; this prints help without loading an adapter.

The normal loop is **discover → prepare → inspect → run → inspect failures**.
The manager owns process supervision, logs, dependency gates, cleanup and recovery,
so a caller does not need to reconstruct commands or parse entire build logs.
Commands never prompt for interactive input.

To explicitly retry an uncertain device installation, prepare a separate plan:

```sh
build-manager retry-device /path/to/original-run --step DEVICE_INSTALL_STEP --output /path/to/new-retry-plan.json
```

Inspect it with `show-plan`, then use the normal `run --confirm`, `review` and
`resume --confirm --approval-identity STEP=SHA256` sequence. This reuses the exact
prepared app and creates fresh receipts. The original unknown result stays
unchanged; other deliveries do not repeat. This command does not retry uploads.

## Discover supported work

```sh
build-manager add /path/to/project
build-manager list
build-manager capabilities --project REGISTRATION_ID
build-manager inputs --project REGISTRATION_ID
```

`add` authorizes the checkout's adapter. `capabilities` reads its descriptor and
returns host-specific `targets` mapping target → operation → backend choices,
plus the descriptor's suites, run fields and combined journey capability. It does
not execute project code. `inputs` explicitly queries the trusted adapter for
non-secret defaults and dynamic choices, such as device IDs.

If automatic storage maintenance reports a stale registration, inspect the current
adapter before explicitly refreshing its recorded identity:

```sh
build-manager inspect REGISTRATION_ID
build-manager show-plan /path/to/retained-plan.json
build-manager trust REGISTRATION_ID
```

Compare the current descriptor digest and project ID with the plan's `adapter`
identity before using `trust` for retained work. Use the same `--registry` directory
for every command. `trust` records the reviewed descriptor; it does not execute
maintenance or change any retained phase outcome. A changed adapter cannot be
approved for an old plan by refreshing registration: restore and review the
original adapter or prepare a fresh plan. Do not replay a workload solely to clear
a maintenance warning. Use the storage inventory and explicit cleanup commands
below when cleanup is needed independently.

In the window, **More → Add project** lets you review and add the same registered
checkout again with its existing registration name to refresh its recorded
descriptor. Review the displayed checkout and descriptor before adding it; existing unknown run outcomes remain unchanged.

Use the IDs and case-sensitive names returned by discovery. Omitting `--project`
uses the selected registration. Put `--registry /private/config` **before** the
command to use a separate manager configuration directory.

## Run a project preset

GUI and CLI use the same saved project presets in the private registry. Discover
and inspect them with `build-manager presets --project "Project name"`. Project
selectors accept a unique registration ID, project ID, name or checkout path.
Ambiguous names fail instead of choosing a checkout.

```sh
build-manager presets --project "Project name"
build-manager plan --project "Project name" --preset "Daily validation" --output /tmp/preset-plan.json
build-manager show-plan /tmp/preset-plan.json
build-manager start --project "Project name" --preset "Daily validation"
```

`start` prepares fresh source/settings from the preset and runs the result. Its
optional `--output NEW_DIRECTORY` selects a fresh run directory; otherwise it
allocates one under the project's result root. Delivery still pauses for exact
artifact/recipient review and uses ordinary `review`/`resume`; saved presets never
contain approvals. `--confirm` remains necessary for a plan with an overall
external effect. Use `plan --preset` followed by ordinary `run` when you need to
inspect the complete plan before execution. Preset planning rejects explicit
operation/host/source overrides rather than silently mixing configurations. Both
`plan --preset` and `start --preset` accept explicit `--run-value field=value`
for declared per-run inputs, such as tester notes or recipient choices. These
replace matching saved inputs for this plan only; other saved inputs remain and
the preset is unchanged. Unknown fields and secret values are rejected through
the normal input validation before project planning.

Save choices using the same selection schema as the GUI:

```sh
build-manager save-preset "Daily validation" --project "Project name" --file choices.json
```

The JSON contains either advanced `operation`, `platform`, `backend` and optional
`suite`/`run_options`, or a `goal` (`validate`/`deliver`), `selected_platforms`,
`selected_destinations` and `platform_backends`. Both accept `revision`,
`build_override`, `release_tag` and string-valued `run_overrides`. Secrets remain
protected references. Existing names need `--replace`. Presets are project scoped;
saved names take precedence over same-named descriptor suggestions. These commands
do not change the currently selected GUI form or other projects' presets.

The GUI's Build-only preset goal is not currently accepted by CLI preset
preparation. For command-line build-only work, discover the project's `Build`
operation and prepare it explicitly with `plan --operation Build` and the declared
target/backend. Inspect that plan's effects before running it.

## Prepare and run

The following target, operation, backend and suite are examples; replace them
with the project's declared values.

```sh
build-manager plan --project REGISTRATION_ID \
  --operation Check --target native --backend Local \
  --suite portable.contracts --revision working-tree \
  --run-value 'notes=Check this change' --output /tmp/check-plan.json
build-manager show-plan /tmp/check-plan.json
build-manager run /tmp/check-plan.json --output /tmp/check-run \
  --expect-identity PLAN_SHA256
```

`plan` returns `identity` and the saved plan path. Use that identity with
`--expect-identity` to reject changes after inspection. Read source, commands,
settings, effects, destinations and dependencies from `show-plan` before running.
Preparation invokes trusted project code and may create a source snapshot; it
does not execute the plan's phases. Plans are trusted executable configuration.

`run` blocks until completion, cancellation or delivery review. Use a fresh output
directory for each run. Its default output is one compact JSON object, with no
child console chatter. It includes overall status, per-step status/exit code,
errors, failure summaries, failed test samples and paths to the retained report
and logs. With `--events`, stdout is JSONL: event envelopes followed by the final
result. Events wrap existing executor events in `event`; child output is an
`event.type="output"` string, never raw text between JSON records.
Credential filtering scans the environment once per record, including large test
inventories; private-key block state remains local to each independent string.

`--run-value NAME=VALUE` can be repeated for declared non-secret input fields.
Values remain strings; choice fields use their declared keys and multiselect
fields use JSON arrays, for example `--run-value 'devices=["device-id"]'`.
An equals sign inside a value is preserved. Duplicate keys and malformed
assignments fail before invoking the adapter. Credentials use protected references,
not inline tokens or passwords. Do not pass shell command strings to the manager.

## Read only the evidence needed

```sh
build-manager status /tmp/check-run
build-manager logs /tmp/check-run --step check --tail-lines 40 --max-bytes 16384
build-manager status /tmp/check-run --full
build-manager history --project REGISTRATION_ID --limit 20
```

Start with the compact result. Read a failing step's tail next, and request the
full report only when needed. Log reads default to 40 lines/16 KiB and are capped
at 1,000 lines/64 KiB. `truncated` reports omitted output; a byte boundary can leave
a partial first line. The retained log still contains the full redacted output.
Compact summaries cap each diagnostic at 3,000 characters and include at most
20 failing cases per step, with each case field capped at 2,000 characters.
History reads up to 100 recent runs from the project's declared result directory.
A custom output outside that directory is accessible by path but absent from history.

SIGINT or SIGTERM requests cooperative cancellation and owned process cleanup.
Buffered output is drained after one owned process-stop sequence; it does not
repeat the cleanup grace for each queued line. Wait for the final result before
resuming. Status can also read an active run's
persisted snapshot from another process; it does not wait for completion.
`logs` can read an active phase after its worker creates the log, including older
active intent records that do not yet contain completed log metadata.

## Prepare and continue delivery

For projects declaring combined journeys:

```sh
build-manager journey --project REGISTRATION_ID --goal deliver \
  --platform ios --platform android --destination testers \
  --execution ios=Local --revision COMMIT --output /tmp/delivery-plan.json
build-manager show-plan /tmp/delivery-plan.json
build-manager run /tmp/delivery-plan.json --output /tmp/delivery-run \
  --expect-identity PLAN_SHA256
build-manager review /tmp/delivery-run
```

Choose only declared platforms, destinations and execution hosts. A plan whose
overall effect is external also needs `--confirm` to start. Integrated workflows
can prepare tests/builds and then return `status="awaiting_review"` with exit 3.
`review` verifies retained prerequisites and original artifacts, and returns the
full plan, prerequisite artifact paths/hashes and pending step review identities.
Read the exact source, destination and artifact evidence, obtain authorization
appropriate to that action, then continue with the returned step identity:

```sh
build-manager resume /tmp/delivery-run --confirm \
  --expect-identity PLAN_SHA256 --approval-identity deliver=REVIEW_SHA256
```

Repeat `--approval-identity` for independently reviewed pending steps. `--confirm`
alone does not approve these steps. Review identities bind the retained plan and
artifacts and are rechecked immediately before continuation. Copying an identity
is not authorization from the user. Changed artifacts, mismatched plans and unpassed
gates block their dependent actions. An uncertain external outcome stays frozen,
including its consumers; independent reviewed actions can continue. Review lists
these steps in `unresolved_steps`, and the run remains unknown until reconciled.
Read the
[recovery contract](workflows.md) before retrying external work.

A harmless failed run can use `build-manager resume /tmp/check-run`; passed gates
are reused when their evidence still matches. After `status="unknown"`, follow
the project's reconciliation procedure before attempting another delivery. The
CLI does not provide a force/retry option that bypasses this check.

A cleanup pass from an earlier skipped owner is not a completion guard for a new
attempt. Resume refreshes successful nonexternal cleanup and consumers whose
success dependencies or completion-order prerequisites will run again. This can
include a previously passed runtime check after its preceding owner cleanup is
rescheduled. Unaffected host proofs remain retained. Completed or unknown
external actions are never automatically repeated; a stale external cleanup
requires separate outcome review rather than automatic replay.

## Retry an uncertain device installation

Use this only after deciding to install the same prepared app on the same device
again. The original installation may already have completed. Obtain the exact
unknown installation step ID from `status --full`, then prepare a separate plan:

```sh
build-manager retry-device /tmp/original-run --step INSTALL_STEP --output /tmp/retry-plan.json
build-manager show-plan /tmp/retry-plan.json
build-manager run /tmp/retry-plan.json --output /tmp/retry-run --confirm --expect-identity PLAN_SHA256
build-manager review /tmp/retry-run
```

Choose new plan and result paths. Preparation verifies passed prerequisites and
retained artifact checksums. The retry plan verifies the original run again before
installation and writes new receipt paths. It preserves the original unknown
outcome, does not rebuild the app and does not repeat other deliveries.

CLI preparation leaves the installation awaiting review after the verification
step. Inspect the returned review identity, then use `resume --confirm` with the
retry plan identity and `--approval-identity INSTALL_STEP=REVIEW_SHA256` as in the
delivery sequence above. `--confirm` alone cannot approve the installation.
Eligibility requires an unknown `deploy` step with passed prerequisites, retained
prepared artifacts and declared receipt paths present as command arguments.
Uploads, failed preparation and active runs are ineligible. Changed original
reports or prepared bytes block execution; this is not a general force-retry path.
The GUI's explicit Retry install click supplies authorization for its separate
attempt, so it does not show this additional CLI review sequence.

## Continuing after manager maintenance

An engine or dependency checkout change blocks ordinary `resume`. Run `review`
again and inspect `engine_change.previous`, `engine_change.current` and the
review identity. After reviewing the actual changes and deciding that retained
project results remain applicable, pass `--engine-review-identity SHA256` to
`resume`. A stale identity is rejected. This is a deliberate operator decision,
never an automatic retry or acceptance of a failing test.

The run records the old/new identities, review time and retained phase IDs in
`engine_history`; original phase times and artifacts remain intact. Source,
artifact checksums, pending delivery approvals and unknown-outcome recovery still
apply. The review accepts only the exact engine pair; another change requires
another review. Start a new run when previous results are no longer applicable.

## JSON and exit codes

All normal responses have `cli_schema: 1`, `command` and `ok`. Existing registration
and planning fields remain at the top level. Errors are JSON on stdout with
`error.code` and `error.message`. Diagnostics from dependencies may still appear
on stderr; do not parse stderr as the protocol. `--help` uses ordinary help text.

| Exit | Meaning |
| --- | --- |
| 0 | Request succeeded; run/resume completed with `passed` |
| 1 | Preparation/preflight error, failed run or unknown external outcome |
| 2 | Invalid command-line syntax |
| 3 | Run/resume paused awaiting artifact/destination review |
| 130 | Cancelled request or run |

Read-only commands return 0 when they successfully read evidence, even when that
run failed. Inspect `status` to understand the recorded outcome. `ok` on
run/resume means the run passed; on inspection commands it means the read succeeded.
Keep `result.json`, `plan.json` and logs for recovery. Do not turn a nonzero exit
into an automatic blind retry.

For callers in Python, see the [automation API](../development/automation-api.md).

For a project destination that explicitly supports device-only delivery, omit
`--platform` from `journey --goal deliver` to select no tests. The project still
validates that selection; provider releases or destinations requiring tests reject
it. Tests explicitly selected remain prerequisites of dependent delivery.

## Clean up generated outputs

`build-manager storage --project "Project name"` asks the trusted project adapter
for its owned output inventory. Entries identify their cleanup group, direct child
name and active/pinned protection. Projects without storage support report an
unsupported adapter action; the manager never scans arbitrary folders.

After reviewing the inventory, remove selected outputs with repeated
`--delete 'GROUP=NAME' --confirm`. The project revalidates ownership, pins and
active leases under the same locks used by its GUI cleanup. Manual cleanup may
remove recent outputs; automatic retention age/count rules remain unchanged.

Retire a superseded saved run with `build-manager storage --project PROJECT
--retire-workflow RUN_NAME --confirm`. Use the direct run-directory name shown
by `history`. Retirement releases only that run's holds, disables continuation,
and preserves logs, receipts and unknown external outcomes. It does not delete
outputs or authorize a replacement delivery. Retire workflows separately from
`--delete` selections.

CLI execution invokes a registered project's optional `storage_maintenance`
action after execution leases are released. Its result is saved separately in
`storage-maintenance.json`; maintenance failure does not change the workload's
outcome. The low-level `run_plan` API accepts an explicit `maintenance` callback.
Save needed evidence first. This removes generated artifacts, not installed apps,
signing credentials, build counters or source checkouts.

Delivery presets also accept repeated `--exclude-destination NAME` in `plan` and
`start`. This explicitly omits a selected delivery destination for this run only,
for example an unavailable physical-device destination. All selected platforms and
validation gates stay included, and the saved preset is unchanged. Excluding an
unknown destination or using this option without a delivery preset is rejected.
Inspect `show-plan` to verify the resulting destinations before executing.

## Edit the tracked app version

`build-manager set-version 0.1.16 --project PROJECT` sends an explicit source edit
to the same trusted adapter used by Settings. The project owns version syntax,
which metadata files change and lockfile consistency. This does not save a local
profile, commit source, publish or allocate a provider build number. Review and
commit the edit before preparing a release plan. Unsupported adapters fail rather
than receiving a guessed file edit.

## Continue a ready delivery when another branch fails

`status` and execution results include `continuation.completed_actions`,
`pending_actions`, `failed_steps`, `unknown_steps` and `next_actions`. These expose
individual outcomes even when the complete run fails. Suggested commands are
argument arrays for inspection; reading status does not execute them.

To continue reviewed independent deliveries without repeating failed checks, add
`--no-retry-failed` to `resume`. Failed checks and their blocked consumers remain
failed or skipped in the retained report; this option never approves a delivery
or bypasses its dependencies.

After inspecting the prepared files and destinations with `review`, authorize
specific pending steps directly, without constructing approval JSON or copying
digests:

```sh
build-manager review /path/to/run
build-manager resume /path/to/run --confirm --no-retry-failed --approve-step READY_STEP
```

Repeat `--approve-step` for distinct selected actions. The manager verifies their
retained prerequisite files and binds approvals internally; changed files,
unknown outcomes, completed steps and unrelated blocked deliveries are rejected.
The explicit `--approval-identity STEP=SHA256` interface remains available; do not
combine both forms for the same step. Engine changes still require their separate
explicit review. The overall run and CLI exit remain failed if another required
branch failed, even when this selected delivery succeeds. Read its step outcome
and receipt rather than treating the aggregate failure as a failed delivery.

In the GUI, **Continue ready delivery…** opens the same scoped review. Leave
**Retry failed checks and their blocked steps** unchecked to preserve those
branches, or explicitly select it to retry them. Saved unknown external outcomes
are never repeated automatically. Fresh run approval policy is unchanged.

## Prepare a new delivery from saved inputs

For a project advertising the optional `retained_delivery_plan` action in
`capabilities`, use:

```sh
build-manager retained-delivery /path/to/saved-run --project PROJECT --destination DESTINATION --run-value 'RECIPIENT_FIELD=["saved-device-id"]' --output /path/to/new-plan.json
build-manager show-plan /path/to/new-plan.json
build-manager run /path/to/new-plan.json --output /path/to/new-run --confirm --expect-identity PLAN_SHA256
```

Use the destination and field IDs returned by `capabilities` and `inputs`; repeat
`--destination` and `--run-value` as needed. This prepares a fresh plan without
editing the original run or requiring the current checkout to equal its saved
source. The project verifies the retained snapshot, selected platform's gates,
archive and new recipients. Missing or expired inputs require a fresh build;
unrelated failed platforms do not automatically invalidate a verified platform.
Project policy determines which destinations support reuse and whether export or
provisioning work is needed. Preparation never installs or signs an app.

In the GUI, open the run in History, select **Prepare delivery from saved run…**,
choose destinations and recipients, then **Prepare review plan**. Review the
captured old source and new destination before Start. This optional workflow is
separate from **Retry uncertain device install…**, which repeats the same
uncertain installation and preserves its original unknown outcome.

## Check project tooling before adapter imports

```sh
build-manager tooling --project PROJECT
build-manager tooling --project PROJECT --update --confirm
```

This optional bootstrap protocol works before normal project/settings imports.
The first command is read-only. The second explicitly asks the project to repair
its own tooling to its declared pin and return fresh readiness. Readiness includes
the declared revision and each project-owned interpreter's installed revision
and immutable source provenance. The command returns a nonzero exit while any
required tooling is unavailable or the project reports a blocked active lease.
`check-project` uses this preflight when declared and returns exact suggested
tooling command arrays instead of importing a broken adapter first.

No installer is guessed for unsupported projects. The project owns lockfile
synchronization, explicit tooling enrollment, both-environment installation and
in-flight lease protection. The GUI checkout is never supplied as bootstrap
installation authority. See [setup](setup.md#check-or-repair-project-tooling).
If the project's interpreter is missing, only declared tooling bootstrap actions
can use the existing host Python in isolated mode. This does not create an
environment during status or change the interpreter used for normal project work.

## Scaffold and check a project

For a local command workflow, create a single descriptor in an existing project:

```sh
build-manager init-project /path/to/project --name "My project" --project-id org.example.project --command /path/to/project/.venv/bin/python -m unittest discover
```

Arguments after `--command` belong to the project command. This creates
`build-project.json` exclusively; it never overwrites an existing integration,
registers the project, installs tools or executes the command. Edit `commands.source`
to list the public files/directories needed by the command before preparing work.
The initial source list is empty. See the [command format](../development/project-integration.md).

Then add the folder through the GUI or CLI. For a registered checkout:

```sh
build-manager check-project --project org.example.project
build-manager check-project --project org.example.project --prepare
```

The first command checks files/executable availability and explicitly loads the
trusted adapter's settings protocol. This runs adapter code, but no workload.
The second also prepares every advertised operation/platform/backend combination.
Project preparation can capture sources or prune project-owned outputs; it does
not execute returned plans. Missing platform prerequisites are reported as failed
combinations, not skipped successes. Neither check certifies SDK/native readiness,
publication or an actual test pass. Failed checks return a nonzero exit code.
