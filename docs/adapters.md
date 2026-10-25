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
Moved paths require Locate and renewed trust. A changed descriptor invalidates trust.

Explicit Trust authorizes running reviewed checkout code. This is a trust boundary,
not a sandbox: trusted adapters can execute arbitrary project code. They run under
the declared project interpreter, with manager PYTHONPATH/PYTHONHOME removed, and
exchange schema-1 JSON over stdin/stdout. The manager never imports project modules
or replaces a project's commonUtils pin. The bridge exposes plan/settings/save/
verification actions explicitly. Missing interpreter and API errors are repairable.

Use `build-manager add PATH`, `list`, `inspect REGISTRATION`, `trust REGISTRATION`,
`select REGISTRATION`, `locate REGISTRATION PATH` and `remove REGISTRATION`.
`build-manager plan --project REGISTRATION --operation OP --target TARGET
--backend BACKEND --output PLAN` provides headless parity. Run saved plans through
`python -m build_manager`. GUI checkout switching is disabled while work is active;
selections are stored per registration. Source and destinations remain in each plan.
