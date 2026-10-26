# Adapter contract and ownership

Adapter API 1 returns immutable `Plan`/`Phase` data. Plans declare structured
commands, source identity, dependencies, timeouts, cleanup and owned artifacts.
The headless engine imports neither Qt nor project code. Projects retain their
own interpreters and commonUtils pins, suites, native builders, release gates,
source snapshot policy, app versions, destinations and storage policy.

The manager owns process lifecycle, locking, redaction, generic transports,
profile mechanics, artifact capture and retention mechanisms. Logistics keeps
`Scripts/build_retention.py` as the single policy owner. No alternate project
cache tree is introduced. Shared API documentation belongs in commonUtils.

An engine result records manager and commonUtils commit/dirty identity alongside
adapter-supplied source/toolchain identity. Native transport acceptance is
separate from portable subprocess tests. VM holds are never bypassed by setup.

## Registration and trusted subprocess bridge

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
