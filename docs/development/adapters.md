# Adapter contract and ownership

Start with [the runnable project-test walkthrough](adding-project-tests.md) when
connecting a new project. This page is the protocol and ownership reference.

Run-field descriptors may set `workflow_option: true` for a non-secret choice
that applies to validation, delivery and advanced workflows. Guided views place
these controls with validation settings. They use the existing per-preset
`run_overrides` storage. Restoring a preset without a newly introduced workflow
option resets it to its declared default, rather than inheriting a prior preset's
debug override. Projects own the choice's meaning and enforcement.

Adapter API 1 returns immutable `Plan`/`Phase` data. Plans declare structured
commands, source identity, dependencies, timeouts, cleanup and owned artifacts.
The headless engine imports neither Qt nor project code. Projects retain their
own interpreters and commonUtils pins, suites, native builders, release gates,
source snapshot policy, app versions, destinations and storage policy.

The manager owns process lifecycle, locking, redaction, generic transports,
profile mechanics, artifact capture and retention mechanisms. Logistics keeps
`logistics_build/build_retention.py` as the single policy owner. No alternate project
cache tree is introduced. Shared API documentation belongs in commonUtils.

An engine result records manager and commonUtils commit/dirty identity alongside
adapter-supplied source/toolchain identity. Native transport acceptance is
separate from portable subprocess tests. VM holds are never bypassed by setup.

## Registration and trusted subprocess bridge

Read this contract after the [architecture overview](architecture.md). To trace a
working integration, follow a consumer's `build-project.json` to its bridge and
adapter; do not import its implementation into the manager. The minimum path is
descriptor → registration → isolated planning request → validated Plan → executor.
Use temporary harmless commands while developing that path, before adding native
builders or delivery effects.

Inspection phases may declare `retry_exit_codes` and `retry_delay` (seconds,
default 30). Only those explicitly temporary command failures retry, without a
retry limit; each command retains its bounded timeout. The scheduler releases
workers and resources during the delay, persists the waiting state and attempt
logs, and exposes ready delivery approvals while other recipients wait. Stop
cancels the wait. This policy is restricted to `effect='inspect'` phases;
deployment, upload and publication never gain automatic replay. Keep availability
checks separate from installation, and retain identity/signature/approval checks
immediately before the actual effect. Unused retry fields are omitted from plan
serialization to preserve legacy hashes.

### Opt-in test infrastructure recovery

`Phase.infrastructure_recovery` opts an explicit `effect='test', kind='test'`
unit into one infrastructure recovery per target per run. Existing adapters do
not opt in automatically. The manager owns supervision, deadlines, admission,
evidence and replay limits; the trusted adapter supplies isolated probe and
repair commands using the appropriate lifecycle/transport APIs. It must define
a repeatable test boundary and verify ownership and worker state on that platform.
This contract does not add platform-specific repair commands to existing adapters.

The policy is a dictionary with exactly these fields:

```python
infrastructure_recovery = {
    'environment': 'android',  # 'ios' or 'vm' are also supported
    'target': owned_target_identity,
    'resource': target_resource,
    'safe_to_repeat': True,
    'probe': [project_python, runner, 'probe-test-environment'],
    'recover': [project_python, runner, 'recover-test-environment'],
    'inputs': {absolute_prepared_app_path: prepared_app_sha256},
    'timeout': 120,
}
```

Declare `{target_resource: 1}` in the phase's resources, with capacity one in
the plan. All recovery policies for the same environment/target must use the
same host-wide resource name. The lock remains held through both test attempts,
diagnosis, repair and readiness. Choose a resource identity shared by every
consumer of that target. Declare all prepared inputs needed to bind the repeat
to the same app/payload; the manager checks their SHA-256 before the first test,
before repair and before repeating. Inputs cannot also be declared test outputs.
The test runner must write fresh declared reports for each attempt, using
absolute output paths. Symlink and hard-link aliases of prepared inputs are
also forbidden as test outputs.

The probe is read-only. It exits zero and writes **only one JSON object** to
stdout (maximum 64 KiB), with no stderr output because the supervisor captures
both streams in the same log. Example evidence for a confirmed stopped environment:

```json
{
  "schema": 1,
  "target": "exact-target-identity-from-the-plan",
  "state": "stopped",
  "failure_kind": "infrastructure",
  "owned": true,
  "exclusive": true,
  "worker_stopped": true,
  "held": false
}
```

`state` is `ready`, `stopped`, `disconnected`, or `unknown`. Only `stopped` and
`disconnected`, with `failure_kind='infrastructure'`, permit repair. The probe
must distinguish an app crash from an environment failure using retained test
and platform evidence. A transport timeout, missing job handle, or missing app
result alone does not prove that the guest or worker stopped. Reconcile remote
worker/receipt state first. Known JUnit or streamed test failures, and incomplete
local process cleanup, prevent automatic repair/replay even if a probe would
otherwise authorize it. Unknown ownership, live workers, held VMs and personal
devices must never yield the affirmative proof above.
Reported streamed crashes, failures and timeouts remain recovery vetoes even
when a later final report omits them; the result retains those observations.
For these opted-in test units, a successful command exit that contradicts a
reported failure also remains a failure, including on the repeated attempt.

Hooks receive `BUILD_MANAGER_RECOVERY_TARGET` and
`BUILD_MANAGER_RECOVERY_ACTION`. The action is `probe`, `restart` for a confirmed
stopped target, or `reconnect` for a disconnected target. Repair must recheck
ownership, holds and worker state immediately before mutation and honor the
requested action. Reconnect must not reset a running guest. Restart must use
the owned lifecycle; it must not rebuild the app, reset global simulator/ADB
services, adopt a different device, or touch a personal/held VM. The post-repair
probe must prove `ready` with the same ownership and worker guarantees. No test
starts until that succeeds. Each hook runs through normal cancellation, process
cleanup and redaction; all hooks share the policy timeout (1–600 seconds).
The repeated test has the original phase timeout and exact command/environment.

Each test attempt and hook retains a separate log and artifact directory under
the run's `infrastructure-recovery/`. The result's `recovery` object includes
attempts, checks and status. Admission is persisted before repair; a supervisor
restart cannot reset the target budget. An interrupted admission requires
inspection and a new run. A completed journal can reconcile an interrupted
budget update without running commands again; restored successful phase evidence
rechecks the prepared inputs. Malformed records fail closed. A successful repeat remains `status='passed'`, with
`recovery.status='recovered'` and the visible result “Passed after infrastructure
recovery.” A failed repeat stays failed, and later recovery-enabled phases on
that target are skipped; unrelated targets can continue. Recovery-enabled phases bypass test
evidence caching so retained recovery state cannot be hidden by a cache hit.
Unused policy fields are omitted from serialization to preserve legacy hashes.

Portable contract coverage lives in `test_infrastructure_recovery.py`; it uses
harmless subprocesses and synthetic ownership evidence. Actual emulator/VM
health classification and repair still require adapter integration and separate
native acceptance with explicitly authorized test environments.

A tracked `build-project.json` declares schema 1, adapter API 1, stable project ID,
name, interpreter (a checkout-relative path or mapping by `sys.platform`), bridge
script and capabilities. Inspection parses JSON only. Registration IDs distinguish
two checkouts of the same project; remove registration never deletes project data.
The registry lives in the operating system's private application-config directory.
Moved paths require Locate. Registration authorizes the checkout, including
existing registrations and descriptor updates; Locate retains that authorization.
Descriptor validation and project identity checks still apply.

Adding a project authorizes its adapter code without an additional approval dialog.
Registration is not a sandbox: adapters can execute arbitrary project code. They run under
the declared project interpreter, with manager PYTHONPATH/PYTHONHOME removed, and
exchange schema-1 JSON over stdin/stdout. The manager never imports project modules
or replaces a project's commonUtils pin. The bridge exposes plan/settings/save/
verification actions explicitly. Missing interpreter and API errors are repairable.

Requests also include `settings_profile`, a private per-registration path under
the manager configuration directory, and `manager_checkout`, the active manager
source root. Adapters may use the profile path for local persistence and the
checkout for dedicated-machine discovery. Adapters own legacy-profile migration
and must preserve explicit overrides. These optional context fields do not change
the API-1 action values or authorize VM mutation.

Settings rows may declare `visible_when` as a mapping from field names to expected
text values. The editor evaluates these conditions against unsaved inputs and
combines them with search filtering. Hidden values are retained when saving.

Use `build-manager add PATH`, `list`, `inspect REGISTRATION`,
`select REGISTRATION`, `locate REGISTRATION PATH` and `remove REGISTRATION`.
`trust REGISTRATION` remains a compatibility command; it is no longer required.
`build-manager plan --project REGISTRATION --operation OP --target TARGET
--backend BACKEND --output PLAN` provides headless parity. Run saved plans through
`python -m build_manager`. GUI checkout switching is disabled while work is active;
selections are stored per registration. Source and destinations remain in each plan.

Optional `test_suites` metadata provides applicable named suites in the guided UI;
the selected ID is forwarded through the isolated plan bridge and retained in
adapter identity. The headless planner accepts the same selection with `--suite ID`.
Projects must honor the selection and emit declared `junit`
artifacts for individual case visibility. See the [test organization contract](test-organization.md)
for schema, suite layout, reporting and release-gate adoption requirements.

Optional [journey schema 1](journey-contract.md) adds a single multi-platform
planning request and explicit platform/destination evidence. The GUI and
`build-manager journey` share this contract. Older adapters retain their original
single-platform path; independently prepared plans are never silently merged.


## Isolated guest tool preparation

`build_manager.guest_tools` owns transport-independent preparation programs.
Projects supply every tool/runtime pin; these helpers import no project or Qt code.
`linux_parameters(uv_version=..., python=...)` validates the data consumed by
`LINUX_BOOTSTRAP`. Run that program through the existing owned guest transport as
`python3 -c PROGRAM OWNED_WORKSPACE JSON_PARAMETERS`. It creates a bootstrap venv,
installs the selected uv and creates the isolated project interpreter. Failures
stop before later preparation commands; existing per-command budgets remain.

`windows_parameters(token, tools, python=..., guest_architecture=...,
python_architecture=...)` validates uv/Git HTTPS GitHub archive metadata and
runtime selectors. Supply its result as structured values to the existing
PowerShell transport running `WINDOWS_PREPARE`. The program checks the interactive
account, selected architecture, ownership token and unused workspace; verifies
archive SHA-256 before extraction; then creates the isolated interpreter and
returns the existing preparation receipt. It does not change global PATH or
reuse an unowned workspace. The programs must run only in an explicitly selected
guest under the existing ownership/cleanup lifecycle.

Projects still select guests, archives, interpreter versions and test suites,
retain receipts and collect evidence before cleanup. Preparation is not native
acceptance. First-boot guest provisioning (`vm_bootstrap`) remains a distinct
stage, with its own interpreter and machine-creation lifecycle. Portable tests
execute Linux bootstrap commands through a mocked subprocess boundary and check
Windows parameters/guards; they do not establish native PowerShell execution or
successful downloads in a real guest.


## Interactive deployment compatibility commands

`deployment_commands.Command` carries explicit argv, cwd and optional environment
values. `CommandStep` adds a display label. `run_sequence(steps, starting=...,
continue_after_failure=...)` runs them in order with inherited terminal input.
The default stops at the first failed child; a caller may ask the operator
whether to continue. Its returned failed steps remain failed even if later
commands succeed. Launch errors, input errors and interruption propagate; no
command is automatically retried. `confirmation_input(prompt, marker=...)`
retains the caller's newline-delimited JSON prompt protocol and returns its
literal answer.

This small compatibility path supports existing interactive launchers. It is
separate from the evidence-producing executor, which deliberately uses closed
stdin. It does not grant release acceptance, approve uploads or merge legacy
commands into reviewed plans. Keep artifact verification, signing, devices and
provider eligibility in the project or its declared plan.

The optional Qt module `deployment_commands_ui` supplies `CommandPanel`.
Its policy supplies a fixed set of `CommandAction` keys, `command(action, target)`,
`inventory(text)`, `logs(action)`, `hint`, `confirmation_marker` and
`confirmation_title`. Inventory returns `CommandInventory` with generic
`CommandTarget` labels/values, summary and errors. The panel retains a selected
unavailable target rather than silently choosing a replacement, rebuilds process
environment overrides for each start, decodes streamed UTF-8 across chunk
boundaries and asks before sending a confirmation answer. Malformed requests
are declined and mark the operation failed. Discovery errors remain failures.

Connect `busy_changed` to the surrounding manager controls and call
`set_external_busy` for manager activity. The containing window must refuse to
close while either path is busy. Policy label changes can use `refresh_labels`;
no interpreter, module, platform, group, signing choice or automatic discovery
command is inferred by the panel. Headless imports do not load Qt or a consumer.

Portable second-project fixtures use real harmless subprocesses for ordering,
terminal input, split UTF-8 prompts, Yes/No decisions, malformed prompts, failed
starts and target retention. Native macOS Qt checks exercise the same process
contracts. Neither establishes physical installation or provider acceptance.


## CPython mobile preparation

`cpython_mobile` supplies verified upstream archive extraction/source checking,
pinned offline wheel caches, host-interpreter resolution, Android/iOS compiler
preparation and prepared-receipt validation. Callers supply explicit CPython and
wheel pins, artifact-relative paths, host configure arguments and target choices.
No consumer is imported, no sibling checkout is discovered and headless imports
require only the standard library plus manager modules.

`prepare_android` and `prepare_ios` accept `command(argv, cwd, timeout)`,
`prepare_source(cache, pin)` and `prepare_wheels(cache, download=...)` callbacks.
These let projects select their pins and retain owned process cancellation.
The latter two can wrap `source` and `runtime_wheels`; neither callback selects
payloads or grants acceptance. iOS also accepts the caller's `tree_digest` and
`current_toolchain`, preserving its existing framework identity format.
`validate_ios` checks the recorded revision/archive, toolchain and framework.
Android reuse checks revision/archive/version/target plus host/library hashes.
Changed receipts fail for inspection rather than silently rebuilding.

Preparation uses the supplied cache and existing `mobile-runtime.lock` beside it.
The historical archive, `manager-wheels`, `prepared-manager.json` and
`prepared-manager-ios.json` names remain compatible. No default storage hierarchy
or retention policy is introduced. Compiler setup temporarily updates the process
environment and restores it even on interruption; invoke preparation serially
inside its owning worker, not concurrently from application threads. Projects
retain supported host checks, SDK/OpenSSL choices and storage lifecycle.

`cpython_testbed.prepare_ios` clones the upstream fixture, applies a supplied
adapter, copies a supplied payload and passes explicit arguments to upstream's
`update_test_plan`. `modernize` accepts scene class/source, deployment minimum
and caller adapter checksum; it preserves upstream XCTest setup and refuses
unexpected scene/delegate/project structure. Its receipt records before/after
hashes plus caller and manager adapter checksums. `scene_source` supplies the
reusable Objective-C scene implementation. `normalize_log` removes the upstream
iOS system-log prefix while preserving Unicode and other output.
`ios_build_command` and `android_test_command` return structured commands for
explicit devices; `install_payload_wheels` uses only the supplied cache and
requirements with `--no-index --no-deps`.

Projects own payload composition, dependency/version policy, suite arguments,
manifest/platform/case verification and acceptance, and simulator/device leases
and cleanup. Prepared caches and successful build commands are not native test
evidence. Portable tiny-archive/fake-compiler/testbed fixtures cover cold/reused
preparation, invalid hashes, changed artifacts/toolchains, cancellation and
caller-selected arguments. Consumer tests must verify retained acceptance and
owned cleanup; real native runtime acceptance remains a separate check.

`AppleSimulators.boot` starts the supplied UUID once and waits up to 180 seconds
for `simctl bootstatus`. If that inspection times out, it rechecks inventory and
repeats only `bootstatus`, once with a 30-second limit, for the same uniquely
identified device in `Booted` state. Readiness requires a successful command
exit; partial output or inventory alone cannot satisfy it. A second timeout or
any other state remains a failure. Caller-owned leases and cleanup are unchanged.

## Boundaries when adding another project

Keep generic execution, subprocess ownership, result/review UI, presets, retained
history, artifact verification, transports, provider clients and lease/pruning
mechanics here. Keep portable persistence, resource/index behavior and toolkit
primitives in commonUtils. A project supplies its adapter/descriptor, source and
privacy rules, interpreters/dependency pins, test inventory, native builders,
package/signing/version rules, release gates, recipients and storage policy.
Use an existing manager primitive before copying it into a new project.

`native_commands.command(argv, cwd, timeout, stdout=..., stderr=..., check=...,
failure=...)` supervises a synchronous POSIX session, always retiring descendants
on success, failure, timeout or interruption. It returns the exit code when
`check=False`. The caller retains its tool arguments, log paths and error policy.
This small API is POSIX-specific; Windows plans retain the executor's job owner.

`dependency_sources.verify(checkout, pin, pinned_source=False)` verifies an
explicit manager commit and its real pinned commonUtils submodule. `archive`
accepts that checkout/pin, `zip` or `tar`, and a supplied disposable workspace.
It prepares exact committed sources without private/untracked host files or
resetting the host checkout. The caller owns pin selection, transport and scratch
cleanup; this module creates no independent cache hierarchy. Initial dependency
bootstrap may remain a small project entry point because the manager cannot be
imported before it is installed.

## Explicit cross-consumer acceptance

`python -m build_manager.consumer_acceptance plan --config CONFIG --output NEW_DIR`
prepares an ordinary manager plan from schema-1 JSON. `baseline` is an explicit
shared Git checkout. Each entry in `checks` declares a unique `id`, consumer
`root`, absolute `interpreter`, argument-array `argv` after that interpreter, and
optional `environment`, `shared`, required `branch` and `distributions` metadata.
No sibling checkout, environment, dependency or branch is automatically selected.
For example, a caller-owned local configuration can contain:

```json
{
  "schema": 1,
  "baseline": "/explicit/shared-checkout",
  "checks": [{
    "id": "consumer-portable",
    "root": "/explicit/consumer-checkout",
    "shared": "/explicit/consumer-checkout/Lib/shared",
    "interpreter": "/explicit/consumer-checkout/.venv/bin/python",
    "argv": ["-m", "unittest", "discover", "-s", "tests", "-p", "test_shared*.py"],
    "environment": {"QT_QPA_PLATFORM": "offscreen"}
  }]
}
```

Use trusted project-owned test commands; labels do not sandbox adapter code or
certify native behavior. The prepared plan records baseline/consumer/shared
working identities and each interpreter's OS, version, architecture and requested
package metadata. Run it through `python -m build_manager NEW_DIR/plan.json
--output NEW_DIR/run`. Ordinary execution owns logs, failures and cancellation.
Source/environment verification runs before tests and again after all attempts,
including failed tests. Modified input captures, checkouts, required branches or
interpreters require a fresh plan. A failed check remains failed even when final
identity verification succeeds. Output and retention remain caller-owned.

Consumers can expose an explicit candidate-library test hook. Such a check is
separate from installed/pinned acceptance: it must preserve the consumer namespace
and report the actual candidate source. This planner never updates a pin,
submodule or subtree, and portable compatibility never implies release acceptance.
